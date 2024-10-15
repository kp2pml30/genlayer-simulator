# { "Depends": "genlayer-py-std:test" }

import genlayer.std as gl
from genlayer.py.types import *
from genlayer.py.storage import *


@gl.contract
class MultiTentantStorage:
    """
    Same functionality as UserStorage, but implemented with multiple storage contracts.
    Each user is assigned to a storage contract, and all storage contracts are managed by this same contract.
    This contract does not prevent users from directly interacting with the storage contracts, but it doesn't bother us for testing purposes.
    This is done to test contract calls between different contracts.
    """

    all_storage_contracts: Vec[Address]
    available_storage_contracts: Vec[Address]
    mappings: TreeMap[
        Address, Address
    ]  # mapping of user address to storage contract address

    def __init__(self, storage_contracts: list[str]):
        for el in storage_contracts:
            self.all_storage_contracts.append(Address(el))
            self.available_storage_contracts.append(Address(el))

    @gl.public.view
    def get_available_contracts(self) -> list[str]:
        return [x.as_hex for x in self.available_storage_contracts]

    @gl.public.view
    def get_all_storages(self) -> dict[str, str]:
        return {
            storage_contract.as_hex: gl.ContractAt(storage_contract)
            .view()
            .get_storage()
            .get()
            for storage_contract in self.all_storage_contracts
        }

    @gl.public
    def update_storage(self, new_storage: str) -> None:
        # Assign user to a storage contract if not already assigned
        if gl.message.sender_account not in self.mappings:
            self.mappings[gl.message.sender_account] = self.available_storage_contracts[
                -1
            ]
            self.available_storage_contracts.pop()

        contract_to_use = self.mappings[gl.message.sender_account]
        gl.ContractAt(contract_to_use).emit(gas=100000).update_storage(new_storage)
