import bids.layout
import datalad.api as dlad
from datalad.runner.exception import CommandError
from typing import Dict

BIDS_MERGE_SEARCH_MAX_DEPTH = 10

def commit2entities(ds:dlad.Dataset, ref_branch:str='base') -> Dict:
    try:
        for l in ds.repo.call_git_items_(['diff', '--name-only', ref_branch]):
            if 'sub' in l:
                return bids.layout.parse_file_entities(l)
    except CommandError:
        pass
    raise RuntimeError('cannot determine entities of the new sample of data')
