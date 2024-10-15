# { "Depends": "genlayer-py-std:test" }

import genlayer.std as gl
from genlayer.py.types import *
from genlayer.py.storage import *


def default_dict_int():
    return defaultdict(int)


@gl.contract
class multi_read_erc20:
    balances: TreeMap[Address, TreeMap[Address, u256]]

    @gl.public
    def update_token_balances(
        self, account_address: str, token_contracts: list[str]
    ) -> dict[str, int]:
        for token_contract in token_contracts:
            contract = gl.ContractAt(Address(token_contract))
            balance = contract.view().get_balance_of(account_address).get()
            self.balances.get_or_insert_default(Address(account_address))[
                Address(token_contract)
            ] = balance

    @gl.public.view
    def get_balances(self) -> dict[str, dict[str, int]]:
        return {
            k.as_hex: {k.as_hex: v for k, v in v.items()}
            for k, v in self.balances.items()
        }
