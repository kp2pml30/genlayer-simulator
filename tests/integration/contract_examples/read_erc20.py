# { "Depends": "genlayer-py-std:test" }

import genlayer.std as gl
from genlayer.py.types import *
from genlayer.py.storage import *


@gl.contract
class read_erc20:
    token_contract: Address

    def __init__(self, token_contract: str):
        self.token_contract = Address(token_contract)

    @gl.public.view
    def get_balance_of(self, account_address: str) -> int:
        return (
            gl.ContractAt(self.token_contract)
            .view()
            .get_balance_of(account_address)
            .get()
        )
