# -*- coding: utf-8 -*-

import FreeCAD as App
import FreeCADGui as Gui


def ensure_draft_runtime():
    """
    Inicializa a infraestrutura GUI do Draft sem trocar de Workbench.

    No FreeCAD 1.1.3, Draft_Move espera que App.activeDraftCommand exista.
    Essa variável é criada por DraftTools durante a inicialização normal
    da bancada Draft. Como Direct chama Draft_Move diretamente, precisamos
    inicializar DraftTools explicitamente.
    """
    import DraftTools  # noqa: F401

    # Proteção defensiva caso a API mude ou a importação parcial não crie
    # a variável esperada.
    if not hasattr(App, "activeDraftCommand"):
        App.activeDraftCommand = None

    if not hasattr(Gui, "Snapper"):
        raise RuntimeError(
            "A infraestrutura Draft foi carregada, mas Gui.Snapper não está disponível."
        )

    return True


class DraftMoveAdapter:
    """
    Ponte MVP para o comando oficial Draft_Move.

    Não muda de Workbench; apenas garante que o runtime do Draft tenha sido
    inicializado e então aciona o comando nativo.
    """

    def start(self):
        ensure_draft_runtime()

        # DraftTools já registra Draft_Move, mas esta importação é segura e
        # documenta explicitamente a dependência desta ferramenta.
        from draftguitools import gui_move  # noqa: F401

        Gui.runCommand("Draft_Move")
        return True


class DraftSnapAdapter:
    """Base para o modo Por Pontos próprio das próximas versões."""

    def __init__(self):
        ensure_draft_runtime()

    def snap(self, screenpos, lastpoint=None, active=True, constrain=False):
        return Gui.Snapper.snap(
            screenpos,
            lastpoint=lastpoint,
            active=active,
            constrain=constrain,
            noTracker=False,
        )

    def constrain(self, point, basepoint=None, axis=None):
        return Gui.Snapper.constrain(
            point,
            basepoint=basepoint,
            axis=axis,
        )

    def get_point(self, callback, movecallback=None, last=None, title=None):
        return Gui.Snapper.getPoint(
            last=last,
            callback=callback,
            movecallback=movecallback,
            title=title,
            mode="point",
        )

    def finish(self):
        try:
            Gui.Snapper.off()
        except Exception:
            pass
