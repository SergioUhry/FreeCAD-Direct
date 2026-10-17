# -*- coding: utf-8 -*-
"""Mover por Pontos com resolução estrutural para Part, Body, Link e objetos simples.

Features internas de PartDesign::Body são tratadas pelo Body pai. O modo de
subelementos do Draft mantém o comportamento nativo.
"""

import FreeCAD as App
import FreeCADGui as Gui
import DraftVecUtils

from draftguitools import gui_move
from draftguitools import gui_trackers as trackers
from draftutils.translate import translate

from .adapters.draft import ensure_draft_runtime



# ============================================================
# RESOLUÇÃO EXATA DA SELEÇÃO
# ============================================================

def _is_link(obj):
    if obj is None:
        return False
    tid = str(getattr(obj, "TypeId", ""))
    return tid == "App::Link" or tid.startswith("App::Link")


def _is_body(obj):
    return obj is not None and str(getattr(obj, "TypeId", "")) == "PartDesign::Body"


def _is_app_part(obj):
    return obj is not None and str(getattr(obj, "TypeId", "")) == "App::Part"


def _object_from_subname(root, subname):
    """
    Retorna o DocumentObject mais profundo do caminho selecionado.

    Exemplo real:
        Armação [App::Part]
          -> Chapa_Superior [PartDesign::Body]
             -> Pad004.Face5

    O SelectionEx sem resolução pode trazer ``Armação`` como Object, mas o
    caminho em SubElementNames ainda informa que o usuário selecionou o Body
    ou uma feature abaixo dele. ``getSubObjectList()`` devolve os objetos ao
    longo desse caminho; usamos o último DocumentObject válido.
    """
    if root is None or not subname:
        return root

    # Um Link representa uma ocorrência/instância. Nunca atravessamos o Link
    # para mover/copiar acidentalmente o objeto-fonte.
    if _is_link(root):
        return root

    try:
        path = list(root.getSubObjectList(str(subname)))
    except Exception:
        path = []

    if path:
        # Se houver um App::Link no caminho, a ocorrência é o alvo correto.
        # O restante do caminho pode apontar para o objeto-fonte do Link.
        for obj in reversed(path):
            if _is_link(obj):
                return obj

        for obj in reversed(path):
            if obj is not None and hasattr(obj, "TypeId"):
                return obj

    return root


def _owning_body(obj):
    """Retorna o PartDesign::Body que contém ``obj``, se existir.

    Importante: não sobe além do Body. Assim, um Body que esteja dentro de um
    App::Part continua sendo tratado como Body, e não como o Part inteiro.
    """
    if obj is None:
        return None

    if _is_body(obj):
        return obj

    # Caminho geométrico direto, normalmente suficiente para features de Body.
    current = obj
    visited = set()
    while current is not None:
        key = (
            getattr(getattr(current, "Document", None), "Name", ""),
            getattr(current, "Name", str(id(current))),
        )
        if key in visited:
            break
        visited.add(key)

        try:
            parent = current.getParentGeoFeatureGroup()
        except Exception:
            parent = None

        if parent is None:
            break
        if _is_body(parent):
            return parent

        # Se chegamos num App::Part sem encontrar Body, o objeto é simples
        # dentro do Part e deve continuar sendo tratado como objeto simples.
        if _is_app_part(parent):
            break

        current = parent

    # Fallback para casos em que o vínculo de Body aparece apenas no InList.
    for parent in list(getattr(obj, "InList", []) or []):
        if not _is_body(parent):
            continue
        try:
            if obj in list(parent.Group):
                return parent
        except Exception:
            # Alguns objetos PartDesign não expõem Group de forma uniforme,
            # mas o Body em InList já é evidência suficiente de contenção.
            return parent

    return None


def _logical_target(obj):
    """Aplica a política da ferramenta ao nível exato selecionado."""
    if obj is None:
        return None

    # Link é uma ocorrência. Nunca atravessar para o objeto-fonte.
    if _is_link(obj):
        return obj

    # Seleções explícitas de Part e Body são respeitadas literalmente.
    if _is_app_part(obj) or _is_body(obj):
        return obj

    # Regra principal pedida para PartDesign: nenhuma feature interna é movida
    # ou copiada sozinha. Pad/Pocket/Sketch/etc. carregam o Body completo.
    body = _owning_body(obj)
    if body is not None:
        return body

    # Fora de Body, um objeto simples continua sendo somente ele mesmo.
    return obj


def exact_selected_objects(selection_ex):
    """
    Resolve o clique exato e depois aplica a política estrutural da Direct.

    - Part selecionado -> Part;
    - Body selecionado -> Body;
    - qualquer objeto dentro de Body -> Body pai;
    - objeto simples fora de Body -> próprio objeto;
    - Link -> própria ocorrência.
    """
    result = []
    seen = set()

    for sel in selection_ex or []:
        root = getattr(sel, "Object", None)
        if root is None:
            continue

        subnames = list(getattr(sel, "SubElementNames", []) or [])

        # Seleção direta na árvore normalmente chega sem subelemento.
        candidates = []
        if not subnames:
            candidates.append(root)
        else:
            for subname in subnames:
                candidates.append(_object_from_subname(root, subname))

        for target in candidates:
            target = _logical_target(target)
            if target is None:
                continue

            key = (
                getattr(getattr(target, "Document", None), "Name", ""),
                getattr(target, "Name", str(id(target))),
            )
            if key in seen:
                continue

            seen.add(key)
            result.append(target)

    return result


# ============================================================
# PLACEMENT GLOBAL / PAI
# ============================================================

def _placement_global(obj):
    try:
        return App.Placement(obj.getGlobalPlacement())
    except Exception:
        return App.Placement(obj.Placement)


def _placement_local(obj):
    return App.Placement(obj.Placement)


def _parent_reference(obj):
    """global = parent_reference * local"""
    g = _placement_global(obj)
    l = _placement_local(obj)
    return g * l.inverse()


def _parent_place_for_ghost(obj):
    try:
        return _parent_reference(obj)
    except Exception:
        return App.Placement()


def _move_global_vector(obj, vector):
    """Move um objeto por um vetor GLOBAL, respeitando containers rotacionados."""
    if not hasattr(obj, "Placement"):
        raise RuntimeError(
            "'{}' não possui Placement e não pode ser movido por esta ferramenta.".format(
                getattr(obj, "Label", getattr(obj, "Name", "Objeto"))
            )
        )

    global_before = _placement_global(obj)
    parent_ref = _parent_reference(obj)

    global_after = App.Placement(global_before)
    global_after.Base = global_before.Base + App.Vector(vector)

    obj.Placement = parent_ref.inverse() * global_after


# ============================================================
# CÓPIA COMPLETA
# ============================================================

def _container_parents(obj):
    """Containers diretos aos quais vale a pena religar a cópia."""
    parents = []

    try:
        geo = obj.getParentGeoFeatureGroup()
        if geo is not None:
            parents.append(geo)
    except Exception:
        pass

    for candidate in list(getattr(obj, "InList", []) or []):
        if candidate in parents:
            continue
        try:
            group = list(candidate.Group)
        except Exception:
            group = None
        if group is not None and obj in group:
            parents.append(candidate)

    return parents


def _needs_recursive_copy(obj):
    """Body, Part e containers precisam levar sua estrutura interna junto."""
    if _is_body(obj) or _is_app_part(obj):
        return True

    try:
        if obj.hasExtension("App::OriginGroupExtension"):
            return True
    except Exception:
        pass

    tid = str(getattr(obj, "TypeId", ""))
    if "DocumentObjectGroup" in tid or "GeoFeatureGroup" in tid:
        return True

    # Grupo Python/customizado com filhos explícitos.
    try:
        if len(list(obj.Group)) > 0:
            return True
    except Exception:
        pass

    return False


def _reparent_copy_like_source(source, copied):
    """
    Recoloca a cópia no mesmo container direto quando isso for seguro.

    Não tenta inserir uma feature genérica dentro de PartDesign::Body; esse caso
    já é resolvido copiando o Body como unidade lógica.
    """
    for parent in _container_parents(source):
        if _is_body(parent):
            continue
        add = getattr(parent, "addObject", None)
        if callable(add):
            try:
                add(copied)
                return
            except Exception:
                pass


def copy_complete(obj):
    """Copia o objeto lógico sem desmontar PartDesign::Body em features."""
    doc = obj.Document
    recursive = _needs_recursive_copy(obj)

    copied = doc.copyObject(obj, recursive)
    if copied is None:
        raise RuntimeError(
            "O FreeCAD não conseguiu copiar '{}'.".format(
                getattr(obj, "Label", getattr(obj, "Name", "Objeto"))
            )
        )

    _reparent_copy_like_source(obj, copied)
    return copied


# ============================================================
# BACKEND CHAMADO PELO COMANDO INTERATIVO
# ============================================================

def move_objects_by_name(names, vector, copy=False):
    """
    Função pública usada pelo histórico/undo do comando.

    `names` já contém os objetos lógicos resolvidos pela ferramenta, portanto
    nenhum expansor de grupos do Draft volta a desmontar o Body.
    """
    doc = App.ActiveDocument
    if doc is None:
        return []

    targets = []
    for name in names:
        obj = doc.getObject(str(name))
        if obj is not None:
            targets.append(obj)

    if not targets:
        return []

    vector = App.Vector(vector)
    result = []

    for source in targets:
        target = copy_complete(source) if copy else source
        _move_global_vector(target, vector)
        result.append(target)

    doc.recompute()

    try:
        Gui.Selection.clearSelection()
        for obj in result:
            Gui.Selection.addSelection(obj)
    except Exception:
        pass

    mode = "COPIAR" if copy else "MOVER"
    App.Console.PrintMessage(
        "\n====================================\n"
        "DIRECT - {}\n"
        "====================================\n".format(mode)
    )
    for source, target in zip(targets, result):
        App.Console.PrintMessage(
            "- origem: {} [{}]\n  alvo:   {} [{}]\n".format(
                source.Label,
                source.TypeId,
                target.Label,
                target.TypeId,
            )
        )
    App.Console.PrintMessage(
        "Vetor global: ({:+.3f}, {:+.3f}, {:+.3f}) mm\n"
        "====================================\n".format(
            vector.x, vector.y, vector.z
        )
    )

    return result


# ============================================================
# GUI: Draft Move nativo + backend Direct
# ============================================================

class DirectMoveCommand(gui_move.Move):
    """
    Mantém a experiência do Draft Move, trocando apenas a resolução/cópia.

    Assim continuamos com:
    - Task panel nativo;
    - Snapper nativo;
    - entrada X/Y/Z e distância;
    - Copy checkbox / tecla C;
    - Alt para cópias sucessivas;
    - constraints e atalhos do Draft.
    """

    def _logical_targets(self):
        targets = exact_selected_objects(getattr(self, "selection", []))
        if not targets:
            raise RuntimeError("Nenhum objeto válido foi selecionado.")
        return targets

    def set_ghosts(self):
        # Preserva o modo especial de subelementos do Draft para Wire/Line.
        try:
            if self.ui.isSubelementMode.isChecked():
                return super().set_ghosts()
        except Exception:
            pass

        for ghost in getattr(self, "ghosts", []):
            try:
                ghost.remove()
            except Exception:
                try:
                    ghost.finalize()
                except Exception:
                    pass

        targets = self._logical_targets()
        places = [_parent_place_for_ghost(obj) for obj in targets]

        self.ghosts = [
            trackers.ghostTracker(
                targets,
                parent_places=places,
            )
        ]

        App.Console.PrintMessage(
            "[Direct] Seleção exata: {}\n".format(
                ", ".join(
                    "{} [{}]".format(obj.Label, obj.TypeId)
                    for obj in targets
                ),
            )
        )

    def move(self, copy):
        # Se o usuário ativar edição de subelemento do Draft, mantém o backend nativo.
        try:
            if self.ui.isSubelementMode.isChecked():
                return super().move(copy)
        except Exception:
            pass

        targets = self._logical_targets()
        names = [obj.Name for obj in targets]

        cmd_name = translate("draft", "Copy" if copy else "Move")

        Gui.addModule("uhrydirect.move")

        vector_text = DraftVecUtils.toString(self.vector)
        cmd = (
            "uhrydirect.move.move_objects_by_name("
            + repr(names)
            + ", "
            + vector_text
            + ", copy="
            + str(bool(copy))
            + ")"
        )

        self.commit(
            cmd_name,
            [cmd, "FreeCAD.ActiveDocument.recompute()"],
        )


class MoveByPointsTool:
    """Entrada usada pelo comando da bancada Direct."""

    def start(self):
        try:
            ensure_draft_runtime()

            # Evita que duas ferramentas Draft concorram entre si.
            previous = getattr(App, "activeDraftCommand", None)
            if previous is not None:
                try:
                    previous.finish()
                except Exception:
                    pass

            command = DirectMoveCommand()

            # Referência extra defensiva; o Draft também registra a ferramenta
            # em App.activeDraftCommand durante Activated().
            Gui._DirectMoveCommand = command

            command.Activated()
            return True

        except Exception as exc:
            App.Console.PrintError(
                "Direct — Mover por Pontos não iniciou: {}\n".format(exc)
            )
            return False
