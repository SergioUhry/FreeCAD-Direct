# -*- coding: utf-8 -*-
import FreeCAD as App
import FreeCADGui as Gui
from .adapters.freecad_113 import NativeTransform113Adapter

class NativeTransformAdapter:
    """Não abre transação própria: o FreeCAD é dono do fluxo nativo."""
    def __init__(self):
        self.adapter = NativeTransform113Adapter()

    def begin(self):
        if len(Gui.Selection.getSelection()) != 1:
            App.Console.PrintError("Direct — Manipulador: selecione exatamente um objeto.\n")
            return False
        try:
            return self.adapter.begin()
        except Exception as exc:
            App.Console.PrintError("Direct — não foi possível abrir o Manipulador: {}\n".format(exc))
            return False

    def accept(self):
        return self.adapter.accept()

    def cancel(self):
        return self.adapter.cancel()
