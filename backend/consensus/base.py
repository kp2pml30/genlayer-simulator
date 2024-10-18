# backend/consensus/base.py

DEFAULT_VALIDATORS_COUNT = 5
DEFAULT_CONSENSUS_SLEEP_TIME = 5

import asyncio
from collections import deque
import json
import traceback
from typing import Callable, Iterator

from sqlalchemy.orm import Session
from backend.consensus.vrf import get_validators_for_transaction
from backend.database_handler.chain_snapshot import ChainSnapshot
from backend.database_handler.contract_snapshot import ContractSnapshot
from backend.database_handler.transactions_processor import (
    TransactionsProcessor,
    TransactionStatus,
)
from backend.database_handler.accounts_manager import AccountsManager
from backend.database_handler.types import ConsensusData
from backend.domain.types import (
    Transaction,
    TransactionType,
    transaction_from_dict,
    LLMProvider,
    Validator,
)
from backend.node.base import Node
from backend.node.types import ExecutionMode, Receipt, Vote
from backend.protocol_rpc.message_handler.base import MessageHandler
from backend.protocol_rpc.message_handler.types import (
    LogEvent,
    EventType,
    EventScope,
)


def node_factory(
    validator: dict,
    validator_mode: ExecutionMode,
    contract_snapshot: ContractSnapshot,
    leader_receipt: Receipt | None,
    msg_handler: MessageHandler,
    contract_snapshot_factory: Callable[[str], ContractSnapshot],
) -> Node:
    return Node(
        contract_snapshot=contract_snapshot,
        validator_mode=validator_mode,
        leader_receipt=leader_receipt,
        msg_handler=msg_handler,
        validator=Validator(
            address=validator["address"],
            stake=validator["stake"],
            llmprovider=LLMProvider(
                provider=validator["provider"],
                model=validator["model"],
                config=validator["config"],
                plugin=validator["plugin"],
                plugin_config=validator["plugin_config"],
            ),
        ),
        contract_snapshot_factory=contract_snapshot_factory,
    )


class ConsensusAlgorithm:
    def __init__(
        self,
        get_session: Callable[[], Session],
        msg_handler: MessageHandler,
    ):
        self.get_session = get_session
        self.msg_handler = msg_handler
        self.queues: dict[str, asyncio.Queue] = {}

    def run_crawl_snapshot_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._crawl_snapshot())
        loop.close()

    async def _crawl_snapshot(self):
        while True:
            with self.get_session() as session:
                chain_snapshot = ChainSnapshot(session)
                pending_transactions = chain_snapshot.get_pending_transactions()
                for transaction in pending_transactions:
                    transaction = transaction_from_dict(transaction)
                    address = transaction.to_address or transaction.from_address

                    if address not in self.queues:
                        self.queues[address] = asyncio.Queue()
                    await self.queues[address].put(transaction)
            await asyncio.sleep(DEFAULT_CONSENSUS_SLEEP_TIME)

    def run_consensus_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._run_consensus())
        loop.close()

    async def _run_consensus(self):
        asyncio.set_event_loop(asyncio.new_event_loop())
        # watch out! as ollama uses GPU resources and webrequest aka selenium uses RAM
        # TODO: async sessions would be a good idea to not block the current thread
        while True:
            try:
                async with asyncio.TaskGroup() as tg:
                    for queue in [q for q in self.queues.values() if not q.empty()]:
                        # sessions cannot be shared between coroutines, we need to create a new session for each coroutine
                        # https://docs.sqlalchemy.org/en/20/orm/session_basics.html#is-the-session-thread-safe-is-asyncsession-safe-to-share-in-concurrent-tasks
                        transaction: Transaction = await queue.get()
                        with self.get_session() as session:

                            def contract_snapshot_factory(
                                contract_address,
                                session=session,
                                transaction=transaction,
                            ):
                                if (
                                    transaction.type == TransactionType.DEPLOY_CONTRACT
                                    and contract_address.lower()
                                    == transaction.to_address.lower()
                                ):
                                    ret = ContractSnapshot(None, session)
                                    ret.contract_address = transaction.to_address
                                    ret.contract_code = transaction.data[
                                        "contract_code"
                                    ]
                                    ret.encoded_state = {}
                                    return ret
                                return ContractSnapshot(contract_address, session)

                            async def exec_transaction_with_session_handling():
                                await self.exec_transaction(
                                    transaction,
                                    TransactionsProcessor(session),
                                    ChainSnapshot(session),
                                    AccountsManager(session),
                                    contract_snapshot_factory,
                                )
                                session.commit()

                            tg.create_task(exec_transaction_with_session_handling())

            except Exception as e:
                print("Error running consensus", e)
                print(traceback.format_exc())
            await asyncio.sleep(DEFAULT_CONSENSUS_SLEEP_TIME)

    async def exec_transaction(
        self,
        transaction: Transaction,
        transactions_processor: TransactionsProcessor,
        snapshot: ChainSnapshot,
        accounts_manager: AccountsManager,
        contract_snapshot_factory: Callable[[str], ContractSnapshot],
        node_factory: Callable[
            [
                dict,
                ExecutionMode,
                ContractSnapshot,
                Receipt | None,
                MessageHandler,
                Callable[[str], ContractSnapshot],
            ],
            Node,
        ] = node_factory,
    ):
        msg_handler = self.msg_handler.with_client_session(
            transaction.client_session_id
        )
        if (
            transactions_processor.get_transaction_by_hash(transaction.hash)["status"]
            != TransactionStatus.PENDING.value
        ):
            # This is a patch for a TOCTOU problem we have https://github.com/yeagerai/genlayer-simulator/issues/387
            # Problem: Pending transactions are checked by `_crawl_snapshot`, which appends them to queues. These queues are consumed by `_run_consensus`, which processes the transactions. This means that a transaction can be processed multiple times, since `_crawl_snapshot` can append the same transaction to the queue multiple times.
            # Partial solution: This patch checks if the transaction is still pending before processing it. This is not the best solution, but we'll probably refactor the whole consensus algorithm in the short term.
            print(" ~ ~ ~ ~ ~ TRANSACTION ALREADY IN PROCESS: ", transaction)
            return

        print(" ~ ~ ~ ~ ~ EXECUTING TRANSACTION: ", transaction)

        # If transaction is a transfer, execute it
        # TODO: consider when the transfer involves a contract account, bridging, etc.
        if transaction.type == TransactionType.SEND:
            return ConsensusAlgorithm.execute_transfer(
                transaction, transactions_processor, accounts_manager, msg_handler
            )

        # Select Leader and validators
        all_validators = snapshot.get_all_validators()
        if not all_validators:
            print(
                "No validators found for transaction, waiting for next round: ",
                transaction,
            )
            return

        involved_validators = get_validators_for_transaction(
            all_validators, DEFAULT_VALIDATORS_COUNT
        )

        for validators in rotate(involved_validators):
            # Update transaction status
            ConsensusAlgorithm.dispatch_transaction_status_update(
                transactions_processor,
                transaction.hash,
                TransactionStatus.PROPOSING,
                msg_handler,
            )

            [leader, *remaining_validators] = validators

            if transaction.leader_only:
                remaining_validators = []

            num_validators = len(remaining_validators) + 1

            contract_snapshot_supplier = lambda: contract_snapshot_factory(
                transaction.to_address.lower()
            )

            leaders_contract_snapshot = contract_snapshot_supplier()

            # Create Leader
            leader_node = node_factory(
                leader,
                ExecutionMode.LEADER,
                leaders_contract_snapshot,
                None,
                msg_handler,
                contract_snapshot_factory,
            )

            # Leader executes transaction
            leader_receipt = await leader_node.exec_transaction(transaction)

            if leader_receipt.error is not None:
                # FIXME
                msg_handler.send_message(
                    LogEvent(
                        "leader execution failed",
                        EventType.ERROR,
                        EventScope.GENVM,
                        "Leader execution failed",
                        leader_receipt.to_dict(),
                    )
                )
                ConsensusAlgorithm.dispatch_transaction_status_update(
                    transactions_processor,
                    transaction.hash,
                    TransactionStatus.UNDETERMINED,
                    msg_handler,
                )
                return

            votes = {leader["address"]: leader_receipt.vote.value}
            # Update transaction status
            ConsensusAlgorithm.dispatch_transaction_status_update(
                transactions_processor,
                transaction.hash,
                TransactionStatus.COMMITTING,
                msg_handler,
            )

            # Create Validators
            validator_nodes = [
                node_factory(
                    validator,
                    ExecutionMode.VALIDATOR,
                    contract_snapshot_supplier(),
                    leader_receipt,
                    msg_handler,
                    contract_snapshot_factory,
                )
                for validator in remaining_validators
            ]

            # Validators execute transaction
            validation_tasks = [
                (
                    validator.exec_transaction(transaction)
                )  # watch out! as ollama uses GPU resources and webrequest aka selenium uses RAM
                for validator in validator_nodes
            ]
            validation_results = await asyncio.gather(*validation_tasks)

            for i, validation_result in enumerate(validation_results):
                votes[validator_nodes[i].address] = validation_result.vote.value
            ConsensusAlgorithm.dispatch_transaction_status_update(
                transactions_processor,
                transaction.hash,
                TransactionStatus.REVEALING,
                msg_handler,
            )

            if (
                len([vote for vote in votes.values() if vote == Vote.AGREE.value])
                >= num_validators // 2
            ):
                break  # Consensus reached

            print(
                "Consensus not reached for transaction, rotating leader: ", transaction
            )

        else:  # this block is executed if the loop above is not broken
            print("Consensus not reached for transaction: ", transaction)
            msg_handler.send_message(
                LogEvent(
                    "consensus_failed",
                    EventType.ERROR,
                    EventScope.CONSENSUS,
                    "Failed to reach consensus",
                )
            )
            ConsensusAlgorithm.dispatch_transaction_status_update(
                transactions_processor,
                transaction.hash,
                TransactionStatus.UNDETERMINED,
                msg_handler,
            )
            return

        ConsensusAlgorithm.dispatch_transaction_status_update(
            transactions_processor,
            transaction.hash,
            TransactionStatus.ACCEPTED,
            msg_handler,
        )

        final = False
        consensus_data = ConsensusData(
            final=final,
            votes=votes,
            leader_receipt=leader_receipt,
            validators=validation_results,
        ).to_dict()

        msg_handler.send_message(
            LogEvent(
                "consensus_reached",
                EventType.SUCCESS,
                EventScope.CONSENSUS,
                "Reached consensus",
                consensus_data,
            )
        )

        # Register contract if it is a new contract
        if transaction.type == TransactionType.DEPLOY_CONTRACT:
            new_contract = {
                "id": transaction.data["contract_address"].lower(),
                "data": {
                    "state": leader_receipt.contract_state,
                    "code": transaction.data["contract_code"],
                },
            }
            leaders_contract_snapshot.register_contract(new_contract)

            msg_handler.send_message(
                LogEvent(
                    "deployed_contract",
                    EventType.SUCCESS,
                    EventScope.GENVM,
                    "Contract deployed",
                    new_contract,
                )
            )

        # Update contract state if it is an existing contract
        else:
            leaders_contract_snapshot.update_contract_state(
                leader_receipt.contract_state
            )

        ConsensusAlgorithm.dispatch_transaction_status_update(
            transactions_processor,
            transaction.hash,
            TransactionStatus.FINALIZED,
            msg_handler,
        )

        # Finalize transaction
        transactions_processor.set_transaction_result(
            transaction.hash,
            consensus_data,
        )

        # Insert pending transactions generated by contract-to-contract calls
        pending_transactions_to_insert = leader_receipt.pending_transactions
        for pending_transaction in pending_transactions_to_insert:
            nonce = transactions_processor.get_transaction_count(transaction.to_address)
            transactions_processor.insert_transaction(
                transaction.to_address,  # new calls are done by the contract
                pending_transaction.address,
                {
                    "calldata": pending_transaction.calldata,
                },
                value=0,  # we only handle EOA transfers at the moment, so no value gets transferred
                type=TransactionType.RUN_CONTRACT.value,
                nonce=nonce,
                leader_only=transaction.leader_only,  # Cascade
                client_session_id=transaction.client_session_id,
                triggered_by_hash=transaction.hash,
            )

    @staticmethod
    def execute_transfer(
        transaction: Transaction,
        transactions_processor: TransactionsProcessor,
        accounts_manager: AccountsManager,
        msg_handler: MessageHandler,
    ):
        """
        Executes a native token transfer between Externally Owned Accounts (EOAs).

        This function handles the transfer of native tokens from one EOA to another.
        It updates the balances of both the sender and recipient accounts, and
        manages the transaction status throughout the process.

        Args:
            transaction (dict): The transaction details including from_address, to_address, and value.
            transactions_processor (TransactionsProcessor): Processor to update transaction status.
            accounts_manager (AccountsManager): Manager to handle account balance updates.
        """

        # If from_address is None, it is a fund_account call
        if not transaction.from_address is None:
            # Get the balance of the sender account
            from_balance = accounts_manager.get_account_balance(
                transaction.from_address
            )

            # If the sender does not have enough balance, set the transaction status to UNDETERMINED
            if from_balance < transaction.value:
                ConsensusAlgorithm.dispatch_transaction_status_update(
                    transactions_processor,
                    transaction.hash,
                    TransactionStatus.UNDETERMINED,
                    msg_handler,
                )
                return

            # Update the balance of the sender account
            accounts_manager.update_account_balance(
                transaction.from_address, from_balance - transaction.value
            )

        # If to_address is None, it is a burn call
        if not transaction.to_address is None:
            to_balance = accounts_manager.get_account_balance(transaction.to_address)

            # Update the balance of the recipient account
            accounts_manager.update_account_balance(
                transaction.to_address, to_balance + transaction.value
            )

        ConsensusAlgorithm.dispatch_transaction_status_update(
            transactions_processor,
            transaction.hash,
            TransactionStatus.FINALIZED,
            msg_handler,
        )

    @staticmethod
    def dispatch_transaction_status_update(
        transactions_processor: TransactionsProcessor,
        transaction_hash: str,
        new_status: TransactionStatus,
        msg_handler: MessageHandler,
    ):
        transactions_processor.update_transaction_status(transaction_hash, new_status)

        msg_handler.send_message(
            LogEvent(
                "transaction_status_updated",
                EventType.INFO,
                EventScope.CONSENSUS,
                f"{str(new_status.value)} {str(transaction_hash)}",
                {
                    "hash": str(transaction_hash),
                    "new_status": str(new_status.value),
                },
            )
        )


def rotate(nodes: list) -> Iterator[list]:
    nodes = deque(nodes)
    for _ in range(len(nodes)):
        yield list(nodes)
        nodes.rotate(-1)
