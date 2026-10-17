# -*- coding: utf-8 -*-

import os
import sys
import importlib
import FreeCAD as App
import FreeCADGui as Gui

from .move import MoveByPointsTool
from .transform import NativeTransformAdapter
from .create_body_on_face import run as create_body_on_face
from .position_piece import run as position_piece
from .draw_on_face import run as draw_on_face
from .convert_to_body import run as convert_to_body
from .piece_from_guides import run as piece_from_guides
from .guide_intersection_snap import run_command as toggle_guide_snap, is_active as guide_snap_is_active
from .guide_line import run as guide_line


COMMAND_IDS = {
    "move_points": "UhryDirect_MovePoints",
    "transform": "UhryDirect_Transform",
    "create_body_face": "UhryDirect_CreateBodyOnFace",
    "position_piece": "UhryDirect_PositionPiece",
    "draw_on_face": "UhryDirect_DrawOnFace",
    "convert_to_body": "UhryDirect_ConvertToBody",
    "piece_from_guides": "UhryDirect_PieceFromGuides",
    "guide_snap": "UhryDirect_GuideIntersectionSnap",
    "guide_line": "UhryDirect_GuideLine",
    "medidor_xyz": "Direct_MedidorXYZ",
    "matriz_leve": "Direct_MatrizLeve",
    "matriz_furacao": "Direct_MatrizFuracao",
    "mover_arvore": "Direct_MoverArvore",
}


# Diretório da bancada.
MOD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _icon(name):
    return os.path.join(
        MOD_DIR,
        "Resources",
        "icons",
        name,
    )


def _run_integrated_module(short_name):
    """Executa uma ferramenta integrada."""
    full_name = __package__ + "." + short_name
    importlib.invalidate_caches()
    if full_name in sys.modules:
        importlib.reload(sys.modules[full_name])
    else:
        importlib.import_module(full_name)


class CmdMovePoints:
    def GetResources(self):
        return {
            "Pixmap": _icon("MovePoints.svg"),
            "MenuText": "Mover por Pontos",
            "ToolTip": (
                "Move por ponto-base e ponto-destino usando a infraestrutura "
                "do Draft."
            ),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        MoveByPointsTool().start()


class CmdTransform:
    def GetResources(self):
        return {
            "Pixmap": _icon("Transform.svg"),
            "MenuText": "Manipulador",
            "ToolTip": (
                "Abre o Transform Manipulator nativo do FreeCAD "
                "(U/V/W, Local/Global, translação e rotação)."
            ),
        }

    def IsActive(self):
        return (
            App.ActiveDocument is not None
            and len(Gui.Selection.getSelection()) == 1
        )

    def Activated(self):
        NativeTransformAdapter().begin()


class CmdCreateBodyOnFace:
    def GetResources(self):
        return {
            "Pixmap": _icon("CreateBodyOnFace.svg"),
            "MenuText": "Criar Body na Face",
            "ToolTip": (
                "Cria um novo PartDesign Body + Sketch independente, "
                "orientado pela face plana selecionada e com zero no "
                "canto inferior esquerdo."
            ),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        create_body_on_face()


class CmdPositionPiece:
    def GetResources(self):
        return {
            "Pixmap": _icon("PositionPiece.svg"),
            "MenuText": "Posicionar Peça",
            "ToolTip": (
                "Posiciona peça por Face→Face ou por Ponto→Ponto. "
                "Selecione primeiro a referência da peça móvel e depois "
                "a referência de destino."
            ),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        position_piece()


class CmdDrawOnFace:
    def GetResources(self):
        return {
            "Pixmap": _icon("DrawOnFace.svg"),
            "MenuText": "Desenhar na Face",
            "ToolTip": (
                "Cria um Sketch independente dentro do Body existente, "
                "orientado pela face selecionada e abre o Sketch para edição."
            ),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        draw_on_face()


class CmdConvertToBody:
    def GetResources(self):
        return {
            "Pixmap": _icon("ConvertToBody.svg"),
            "MenuText": "Converter para Body",
            "ToolTip": (
                "Converte um sólido comum/importado em PartDesign Body com "
                "Base_Direct interna. Se Sketches também estiverem selecionados, "
                "eles entram no mesmo Body preservando a posição."
            ),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        convert_to_body()


class CmdGuideIntersectionSnap:
    def GetResources(self):
        return {
            "Pixmap": _icon("GuideIntersectionSnap.svg"),
            "MenuText": "Snap Cruzamento de Guias",
            "ToolTip": (
                "Liga/desliga um snap exclusivo para cruzamentos reais entre "
                "Linhas Guia. Selecione primeiro a referencia da peca, "
                "clique no cruzamento e depois use Posicionar Peca."
            ),
            "Checkable": True,
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def IsChecked(self):
        return guide_snap_is_active()

    def Activated(self):
        toggle_guide_snap()


class CmdPieceFromGuides:
    def GetResources(self):
        return {
            "Pixmap": _icon("PieceFromGuides.svg"),
            "MenuText": "Peça pelas Guias",
            "ToolTip": (
                "Cria Body + Sketch a partir de exatamente 4 Linhas Guia "
                "(dois pares paralelos) e abre o Pad nativo."
            ),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        piece_from_guides()


class CmdGuideLine:
    def GetResources(self):
        return {
            "Pixmap": _icon("GuideLine.svg"),
            "MenuText": "Linha Guia",
            "ToolTip": (
                "Linha Guia + medição ao vivo: acompanha a ponta do mouse, "
                "captura cruzamentos de guias e arestas no plano global ativo. "
                "X/Y/Z trava; digite a medida e Enter para confirmar."
            ),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        guide_line()



class CmdMedidorXYZ:
    def GetResources(self):
        return {
            "Pixmap": _icon("MeasureXYZ.svg"),
            "MenuText": "Medidor XYZ Pro",
            "ToolTip": (
                "Mede a menor distância 3D e as componentes X/Y/Z. "
                "Também permite criar cotas de conferência no 3D."
            ),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        _run_integrated_module("medidor_xyz")


class CmdMatrizLeve:
    def GetResources(self):
        return {
            "Pixmap": _icon("MatrixLight.svg"),
            "MenuText": "Matriz Leve",
            "ToolTip": "Cria e edita matrizes leves, inclusive matriz sobre matriz e par oposto.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        _run_integrated_module("matriz_leve")


class CmdMatrizFuracao:
    def GetResources(self):
        return {
            "Pixmap": _icon("MatrixHole.svg"),
            "MenuText": "Matriz de Furação",
            "ToolTip": "Abre a Matriz de Furação Leve X/Y integrada, mantendo a lógica atual.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        _run_integrated_module("matriz_furacao")


class CmdMoverArvore:
    def GetResources(self):
        return {
            "Pixmap": _icon("MoveTree.svg"),
            "MenuText": "Mover na Árvore",
            "ToolTip": (
                "Reorganiza objetos entre contêineres da árvore preservando "
                "a posição/orientação global."
            ),
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        _run_integrated_module("mover_arvore")


_registered = False


def register_commands():
    global _registered

    if _registered:
        return

    Gui.addCommand(
        COMMAND_IDS["move_points"],
        CmdMovePoints(),
    )

    Gui.addCommand(
        COMMAND_IDS["transform"],
        CmdTransform(),
    )

    Gui.addCommand(
        COMMAND_IDS["create_body_face"],
        CmdCreateBodyOnFace(),
    )

    Gui.addCommand(
        COMMAND_IDS["position_piece"],
        CmdPositionPiece(),
    )

    Gui.addCommand(
        COMMAND_IDS["draw_on_face"],
        CmdDrawOnFace(),
    )

    Gui.addCommand(
        COMMAND_IDS["convert_to_body"],
        CmdConvertToBody(),
    )

    Gui.addCommand(
        COMMAND_IDS["guide_snap"],
        CmdGuideIntersectionSnap(),
    )

    Gui.addCommand(
        COMMAND_IDS["piece_from_guides"],
        CmdPieceFromGuides(),
    )

    Gui.addCommand(
        COMMAND_IDS["guide_line"],
        CmdGuideLine(),
    )

    Gui.addCommand(
        COMMAND_IDS["medidor_xyz"],
        CmdMedidorXYZ(),
    )

    Gui.addCommand(
        COMMAND_IDS["matriz_leve"],
        CmdMatrizLeve(),
    )

    Gui.addCommand(
        COMMAND_IDS["matriz_furacao"],
        CmdMatrizFuracao(),
    )

    Gui.addCommand(
        COMMAND_IDS["mover_arvore"],
        CmdMoverArvore(),
    )

    _registered = True
