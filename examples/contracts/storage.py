# { "Depends": "genlayer-py-std:test" }

import genlayer.std as gl
from genlayer.py.types import *
from genlayer.py.storage import *


# contract class
@gl.contract
class Storage:
    storage: str

    # constructor
    def __init__(self, initial_storage: str):
        self.storage = initial_storage

    # read methods must be annotated with view
    @gl.public.view
    def get_storage(self) -> str:
        return self.storage

    # write method
    @gl.public
    def update_storage(self, new_storage: str) -> None:
        self.storage = new_storage
