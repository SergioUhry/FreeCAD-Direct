# -*- coding: utf-8 -*-
import FreeCADGui as Gui

class TransformTargetResolver:
    @staticmethod
    def selection_ex():
        return Gui.Selection.getSelectionEx("", 0)

    @staticmethod
    def single_object():
        objs = Gui.Selection.getSelection()
        return objs[0] if len(objs) == 1 else None
