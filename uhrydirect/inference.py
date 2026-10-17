# -*- coding: utf-8 -*-
import FreeCAD as App

class InferenceController:
    """trava explícita > magnitude digitada > snap compatível > livre"""
    def __init__(self):
        self.axis_lock = None
    def lock_axis(self, axis):
        axis = axis.upper() if axis else None
        self.axis_lock = axis if axis in ("X", "Y", "Z") else None
    def unlock(self):
        self.axis_lock = None
