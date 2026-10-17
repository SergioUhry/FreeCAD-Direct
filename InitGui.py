# -*- coding: utf-8 -*-

import os
import FreeCADGui
import uhrydirect


class DirectWorkbench(Workbench):
    MenuText = "Direct"
    ToolTip = "Modelagem direta, linhas guia, posicionamento e medição"
    Icon = ""

    def Initialize(self):
        from uhrydirect.commands import register_commands, COMMAND_IDS

        register_commands()

        commands = [
            COMMAND_IDS["create_body_face"],
            COMMAND_IDS["draw_on_face"],
            COMMAND_IDS["convert_to_body"],
            "Separator",
            COMMAND_IDS["move_points"],
            COMMAND_IDS["transform"],
            COMMAND_IDS["position_piece"],
            "Separator",
            COMMAND_IDS["guide_line"],
            COMMAND_IDS["guide_snap"],
            COMMAND_IDS["piece_from_guides"],
            "Separator",
            COMMAND_IDS["medidor_xyz"],
            COMMAND_IDS["matriz_leve"],
            COMMAND_IDS["matriz_furacao"],
            COMMAND_IDS["mover_arvore"],
        ]

        self.appendToolbar("Direct", commands)
        self.appendMenu("Direct", commands)

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def ContextMenu(self, recipient):
        from uhrydirect.commands import COMMAND_IDS

        self.appendContextMenu(
            "Direct",
            [
                COMMAND_IDS["create_body_face"],
                COMMAND_IDS["draw_on_face"],
                COMMAND_IDS["convert_to_body"],
                "Separator",
                COMMAND_IDS["move_points"],
                COMMAND_IDS["transform"],
                COMMAND_IDS["position_piece"],
                "Separator",
                COMMAND_IDS["guide_line"],
                COMMAND_IDS["guide_snap"],
                COMMAND_IDS["piece_from_guides"],
                "Separator",
                COMMAND_IDS["medidor_xyz"],
                COMMAND_IDS["matriz_leve"],
                COMMAND_IDS["matriz_furacao"],
                COMMAND_IDS["mover_arvore"],
                ],
        )

    def GetClassName(self):
        return "Gui::PythonWorkbench"


try:
    _pkg_file = getattr(uhrydirect, "__file__", "") or ""
    _direct_dir = os.path.dirname(os.path.dirname(os.path.abspath(_pkg_file)))
    DirectWorkbench.Icon = os.path.join(
        _direct_dir, "Resources", "icons", "Direct.svg"
    )
except Exception:
    DirectWorkbench.Icon = ""

FreeCADGui.addWorkbench(DirectWorkbench())
