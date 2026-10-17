# -*- coding: utf-8 -*-
import FreeCADGui as Gui

class NativeTransform113Adapter:
    COMMAND = "Std_TransformManip"

    def begin(self):
        Gui.runCommand(self.COMMAND)
        return True

    def _dialog(self):
        dlg = Gui.Control.activeTaskDialog()
        if dlg is None:
            raise RuntimeError("Não há Task Dialog ativo.")
        return dlg

    def accept(self):
        self._dialog().accept()
        return True

    def cancel(self):
        self._dialog().reject()
        return True

    def dialog_content(self):
        return self._dialog().getDialogContent()
