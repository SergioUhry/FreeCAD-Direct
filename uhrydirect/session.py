# -*- coding: utf-8 -*-
class OperationSession:
    IDLE = "idle"
    BASE = "base"
    TARGET = "target"
    CONFIRMING = "confirming"
    FINISHED = "finished"
    CANCELLED = "cancelled"

    def __init__(self, name):
        self.name = name
        self.state = self.IDLE
        self.base_point = None
        self.target_point = None
        self.axis_lock = None
        self.numeric_value = None
