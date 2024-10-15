# { "Depends": "genlayer-py-std:test" }

import genlayer.std as gl
from genlayer.py.types import *
from genlayer.py.storage import *


@gl.contract
class UserStorage:
    storage: TreeMap[str, str]

    # constructor
    def __init__(self):
        pass

    # read methods must be annotated
    @gl.public.view
    def get_complete_storage(self) -> dict:
        return dict(self.storage.items())

    @gl.public.view
    def get_account_storage(self, account_address: str) -> str:
        return self.storage[Address(account_address).as_hex]

    @gl.public
    def update_storage(self, new_storage: str) -> None:
        self.storage[gl.message.sender_account.as_hex] = new_storage
