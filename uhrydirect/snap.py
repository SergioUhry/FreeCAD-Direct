# -*- coding: utf-8 -*-
from .adapters.draft import DraftSnapAdapter

class SnapAdapter:
    """Camada futura para enriquecer o resultado do Draft Snapper."""
    def __init__(self):
        self.draft = DraftSnapAdapter()
    def sample(self, screenpos, lastpoint=None, constrain=False):
        return self.draft.snap(screenpos, lastpoint=lastpoint, active=True, constrain=constrain)
    def finish(self):
        self.draft.finish()
