# -*- coding: utf-8 -*-
"""Snap para cruzamentos reais entre Linhas Guia.

Considera apenas interseções coplanares em 3D e preserva a seleção usada
pelas ferramentas de posicionamento.
"""

import math
import traceback
import copy
import types

import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin

try:
    from PySide import QtCore, QtGui
    QtWidgets = QtGui
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
    except ImportError:
        from PySide6 import QtCore, QtGui, QtWidgets


GUIDE_FLAG = "UhryGuiaReferencia"
DIRECT_GUIDE_FLAG = "DirectGuiaReferencia"
CONTROLLER_ATTR = "_uhry_snap_cruzamento_guias_controller"
SNAP_OBJECT_NAME = "UhrySnapCruzamento"
SNAP_OBJECT_LABEL = "Snap Cruzamento Guias"
COMMAND_ID = "UhryDirect_GuideIntersectionSnap"

# Tolerancias geometricas em mm.
COPLANAR_TOL_MM = 0.05
SEGMENT_TOL_MM = 0.20
DUPLICATE_TOL_MM = 0.05
PARALLEL_EPS = 1e-12

# Raio de captura em pixels na tela.
SNAP_RADIUS_PX = 22.0

# Atualizacao periodica dos cruzamentos. Nao faz recompute no documento.
REFRESH_MS = 700
NATIVE_LOCK_MS = 100

# Comandos do sistema de snap nativo Draft/BIM. Durante o Snap Direct eles
# ficam bloqueados em tempo de execucao; nenhum parametro permanente do
# usuario e alterado. O estado anterior e restaurado ao desligar o Snap Direct.
NATIVE_SNAP_COMMAND_PREFIX = "Draft_Snap_"
NATIVE_SNAP_COMMANDS = {
    "Draft_Snap_Lock",
    "Draft_Snap_Endpoint",
    "Draft_Snap_Midpoint",
    "Draft_Snap_Center",
    "Draft_Snap_Angle",
    "Draft_Snap_Intersection",
    "Draft_Snap_Perpendicular",
    "Draft_Snap_Extension",
    "Draft_Snap_Parallel",
    "Draft_Snap_Special",
    "Draft_Snap_Near",
    "Draft_Snap_Ortho",
    "Draft_Snap_Grid",
    "Draft_Snap_WorkingPlane",
    "Draft_Snap_Dimensions",
}


def unit(v):
    out = App.Vector(v)
    if out.Length < 1e-12:
        raise ValueError("Vetor de comprimento zero.")
    out.normalize()
    return out


def is_guide(obj):
    if obj is None:
        return False
    try:
        props = getattr(obj, "PropertiesList", [])
        return (
            (GUIDE_FLAG in props and bool(getattr(obj, GUIDE_FLAG, False)))
            or (DIRECT_GUIDE_FLAG in props and bool(getattr(obj, DIRECT_GUIDE_FLAG, False)))
        )
    except Exception:
        return False


def guide_shape_global(obj):
    """Le a Shape da guia em coordenadas globais sem duplicar Placement."""
    try:
        shape = Part.getShape(
            obj,
            "",
            needSubElement=False,
            transform=True,
        )
        if shape is not None and not shape.isNull():
            return shape
    except Exception:
        pass

    if not hasattr(obj, "Shape") or obj.Shape is None or obj.Shape.isNull():
        raise ValueError(f"{obj.Label}: guia sem geometria valida.")

    # Linhas Guia sao Part::Feature simples; neste fallback a Shape ja e
    # a melhor representacao disponivel e nao reaplicamos Placement.
    return obj.Shape.copy()


def guide_line_data(obj):
    shape = guide_shape_global(obj)

    if getattr(shape, "ShapeType", "") == "Edge":
        edge = shape
    elif getattr(shape, "Edges", None):
        if len(shape.Edges) != 1:
            raise ValueError(f"{obj.Label}: a guia precisa possuir uma unica aresta.")
        edge = shape.Edges[0]
    else:
        raise ValueError(f"{obj.Label}: guia sem aresta valida.")

    verts = edge.Vertexes
    if len(verts) < 2:
        raise ValueError(f"{obj.Label}: aresta sem dois extremos.")

    p1 = App.Vector(verts[0].Point)
    p2 = App.Vector(verts[-1].Point)
    vec = p2 - p1
    length = vec.Length
    if length < 1e-9:
        raise ValueError(f"{obj.Label}: comprimento zero.")

    d = vec * (1.0 / length)
    return {
        "obj": obj,
        "p1": p1,
        "p2": p2,
        "d": d,
        "length": float(length),
    }


def intersection_of_guides(a, b):
    """
    Cruzamento 3D exato entre dois segmentos de guia.

    Retorna App.Vector ou None.
    Linhas paralelas, reversas na mesma direcao ou linhas que so parecem
    cruzar na tela sao ignoradas.
    """
    p = a["p1"]
    q = b["p1"]
    u = a["d"]
    v = b["d"]

    uxv = u.cross(v)
    denom = uxv.dot(uxv)
    if denom < PARALLEL_EPS:
        return None

    delta = q - p

    # Distancia entre retas no eixo normal comum: elimina cruzamento apenas visual.
    n = unit(uxv)
    if abs(delta.dot(n)) > COPLANAR_TOL_MM:
        return None

    t = delta.cross(v).dot(uxv) / denom
    s = delta.cross(u).dot(uxv) / denom

    pa = p + u * t
    pb = q + v * s
    if (pa - pb).Length > COPLANAR_TOL_MM:
        return None

    # Snap somente onde as duas Linhas Guia desenhadas realmente se cruzam.
    if t < -SEGMENT_TOL_MM or t > a["length"] + SEGMENT_TOL_MM:
        return None
    if s < -SEGMENT_TOL_MM or s > b["length"] + SEGMENT_TOL_MM:
        return None

    return (pa + pb) * 0.5


def capture_intersections(doc):
    guides = [obj for obj in doc.Objects if is_guide(obj)]
    lines = []
    for obj in guides:
        try:
            lines.append(guide_line_data(obj))
        except Exception:
            pass

    hits = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            a = lines[i]
            b = lines[j]
            p = intersection_of_guides(a, b)
            if p is None:
                continue

            duplicate = None
            for existing in hits:
                if (existing["point"] - p).Length <= DUPLICATE_TOL_MM:
                    duplicate = existing
                    break

            pair = (a["obj"], b["obj"])
            if duplicate is not None:
                duplicate["pairs"].append(pair)
            else:
                hits.append({"point": p, "pairs": [pair]})

    return hits


def vec_from_coin(v):
    return App.Vector(float(v[0]), float(v[1]), float(v[2]))


def valid_origin_selection():
    """A ferramenta foi desenhada para origem primeiro, snap em segundo."""
    try:
        sels = Gui.Selection.getSelectionEx("", 0)
    except Exception:
        sels = Gui.Selection.getSelectionEx()

    if len(sels) != 1:
        return False
    if sels[0].Object is None:
        return False
    if getattr(sels[0].Object, "Name", "") == SNAP_OBJECT_NAME:
        return False
    return len(sels[0].SubElementNames) == 1


class SnapGuideIntersections(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.main_window = Gui.getMainWindow()
        self.doc = App.ActiveDocument
        self.view = None
        self.scene = None
        self.active = False

        self.intersections = []
        self.current_hit = None
        self.pending_hit = None

        self.marker_switch = None
        self.marker_coords = None
        self.marker_root = None

        self.status_widget = None
        self.status_label = None

        self.refresh_timer = None
        self.native_lock_timer = None

        self.use_pivy = False
        self.move_cb = None
        self.mouse_cb = None

        # Estado temporario do snap nativo do FreeCAD.
        self.native_snap_state = None
        self.native_snap_actions = {}
        self.native_snap_locked = False
        self.patched_snapper = None
        self.original_snap_method = None

        # Integração com os comandos Draft. O Draft Move obtém pontos por
        # draftguitools.gui_tool_utils.getPoint(); interceptamos esse ponto
        # somente enquanto o Snap Direct estiver ativo.
        self.patched_tool_utils = None
        self.original_getpoint = None
        self.original_getpoint_name = None

    # ----------------------------------------------------
    # SNAP NATIVO DO FREECAD — EXCLUSIVIDADE
    # ----------------------------------------------------

    def _copy_native_value(self, value):
        try:
            return copy.deepcopy(value)
        except Exception:
            try:
                return value.copy()
            except Exception:
                return value

    def _get_snapper(self):
        return getattr(Gui, "Snapper", None)

    def _snapshot_native_snap_state(self):
        """Guarda os modos nativos exatamente como estavam antes do Direct."""
        if self.native_snap_state is not None:
            return

        snapper = self._get_snapper()
        active = []
        if snapper is not None:
            try:
                active = list(getattr(snapper, "active_snaps", []) or [])
            except Exception:
                active = []

        self.native_snap_state = {
            "snapper": snapper,
            "active_snaps": self._copy_native_value(active),
        }

    def _native_toolbar(self, snapper):
        if snapper is None:
            return None
        try:
            toolbar = snapper.get_snap_toolbar()
            if toolbar is not None:
                return toolbar
        except Exception:
            pass
        return getattr(snapper, "toolbar", None)

    def _snapshot_and_lock_toolbar_actions(self, snapper):
        """Desliga visualmente e bloqueia os botoes do Snap Draft."""
        toolbar = self._native_toolbar(snapper)
        if toolbar is None:
            return

        try:
            actions = list(toolbar.actions())
        except Exception:
            return

        for action in actions:
            # Separadores e acoes sem check nao sao modos de snap.
            try:
                if action.isSeparator() or not action.isCheckable():
                    continue
            except Exception:
                continue

            key = id(action)
            if key not in self.native_snap_actions:
                try:
                    checked = bool(action.isChecked())
                except Exception:
                    checked = False
                try:
                    enabled = bool(action.isEnabled())
                except Exception:
                    enabled = True
                self.native_snap_actions[key] = (action, checked, enabled)

            try:
                previous = action.blockSignals(True)
            except Exception:
                previous = None
            try:
                action.setChecked(False)
                action.setEnabled(False)
            except Exception:
                pass
            finally:
                try:
                    action.blockSignals(bool(previous))
                except Exception:
                    pass

    def _disable_native_modes(self, snapper):
        """Desliga os modos nativos pela API oficial do Draft Snapper.

        Nao chama Snapper.off(): o Draft Move precisa que o Snapper continue
        vivo para obter o ponto livre, constraints e entrada numerica. Apenas os
        modos de captura nativos ficam vazios; o Direct injeta seu cruzamento
        no mesmo pipeline de ponto.
        """
        if snapper is None:
            return

        try:
            modes = list(getattr(snapper, "active_snaps", []) or [])
        except Exception:
            modes = []

        toggle = getattr(snapper, "toggle_snap", None)
        if callable(toggle):
            for mode in modes:
                try:
                    toggle(mode, False)
                except Exception:
                    pass

        # Fallback: garante que nenhum modo permaneceu ligado, mesmo em build
        # onde toggle_snap nao esteja disponivel ou tenha falhado.
        try:
            active = getattr(snapper, "active_snaps", None)
            if active is not None:
                try:
                    active.clear()
                except Exception:
                    try:
                        del active[:]
                    except Exception:
                        setattr(snapper, "active_snaps", [])
        except Exception:
            pass

    def _direct_snap_wrapper(self, snapper, screenpos, *args, **kwargs):
        """Wrapper do Snapper.snap usado por comandos Draft (inclusive Move)."""
        original = self.original_snap_method
        if original is None:
            return None

        # Primeiro deixa o Draft calcular ponto livre, plano de trabalho e
        # constraints. Como active_snaps esta vazio, ele nao disputa com o Direct.
        point = original(screenpos, *args, **kwargs)

        if not self.active:
            return point

        try:
            pos = (int(screenpos[0]), int(screenpos[1]))
            hit = self._nearest_hit(pos)
        except Exception:
            hit = None

        if hit is None:
            return point

        p = App.Vector(hit["point"])
        self.current_hit = hit
        self._show_marker(p)

        try:
            # Evita que informacao de um snap nativo anterior seja reaproveitada.
            if hasattr(snapper, "lastSnappedObject"):
                snapper.lastSnappedObject = None
        except Exception:
            pass

        return p

    def _patch_snapper(self, snapper):
        """Integra o Snap Direct ao pipeline de ponto do Draft."""
        if snapper is None:
            return
        if self.patched_snapper is snapper and self.original_snap_method is not None:
            return

        self._restore_snapper_patch()

        try:
            original = snapper.snap
        except Exception:
            return

        self.patched_snapper = snapper
        self.original_snap_method = original

        controller = self

        def wrapped(_snapper, screenpos, *args, **kwargs):
            return controller._direct_snap_wrapper(
                _snapper, screenpos, *args, **kwargs
            )

        try:
            snapper.snap = types.MethodType(wrapped, snapper)
        except Exception:
            self.patched_snapper = None
            self.original_snap_method = None

    def _restore_snapper_patch(self):
        snapper = self.patched_snapper
        original = self.original_snap_method
        self.patched_snapper = None
        self.original_snap_method = None
        if snapper is None or original is None:
            return
        try:
            snapper.snap = original
        except Exception:
            pass

    def _event_position_from_args(self, args, kwargs):
        """Extrai a posição de tela usada pelos comandos Draft."""
        candidates = list(args) + list(kwargs.values())
        for value in candidates:
            if isinstance(value, dict):
                pos = value.get("Position")
                if pos is not None:
                    try:
                        return (int(pos[0]), int(pos[1]))
                    except Exception:
                        pass
        return None

    def _patch_draft_getpoint(self):
        """Injeta o cruzamento no ponto que o Draft Move realmente consome.

        Em FreeCAD 1.1.x o Move chama gui_tool_utils.getPoint(self, event).
        Alterar somente Gui.Snapper.snap não é suficiente em todos os builds,
        portanto a integração é feita no ponto de saída da função de captura.
        """
        if self.original_getpoint is not None:
            return

        try:
            from draftguitools import gui_tool_utils
        except Exception:
            return

        name = None
        original = None
        for candidate in ("getPoint", "get_point"):
            fn = getattr(gui_tool_utils, candidate, None)
            if callable(fn):
                name = candidate
                original = fn
                break

        if original is None:
            return

        controller = self

        def wrapped(*args, **kwargs):
            result = original(*args, **kwargs)
            if not controller.active:
                return result

            pos = controller._event_position_from_args(args, kwargs)
            if pos is None:
                return result

            try:
                hit = controller._nearest_hit(pos)
            except Exception:
                hit = None

            if hit is None:
                return result

            point = App.Vector(hit["point"])
            controller.current_hit = hit
            controller._show_marker(point)

            # getPoint/get_point normalmente retorna (point, ctrlPoint, info).
            # Preservamos todo o restante do retorno e trocamos apenas o ponto.
            if isinstance(result, tuple):
                if len(result) == 0:
                    return result
                return (point,) + tuple(result[1:])
            if isinstance(result, list):
                if not result:
                    return result
                out = list(result)
                out[0] = point
                return out

            # Fallback defensivo para versões que retornem somente o ponto.
            return point

        try:
            setattr(gui_tool_utils, name, wrapped)
        except Exception:
            return

        self.patched_tool_utils = gui_tool_utils
        self.original_getpoint = original
        self.original_getpoint_name = name

    def _restore_draft_getpoint_patch(self):
        module = self.patched_tool_utils
        original = self.original_getpoint
        name = self.original_getpoint_name

        self.patched_tool_utils = None
        self.original_getpoint = None
        self.original_getpoint_name = None

        if module is None or original is None or not name:
            return
        try:
            setattr(module, name, original)
        except Exception:
            pass

    def _enforce_native_snap_exclusive(self):
        if not self.native_snap_locked:
            return

        snapper = self._get_snapper()
        if snapper is None:
            return

        # Mantém o Snapper do Draft vivo e desliga somente os modos nativos.
        # O Mover da Direct recebe o cruzamento diretamente no próprio evento,
        # sem monkey-patch global do Snapper/getPoint.
        self._disable_native_modes(snapper)
        self._snapshot_and_lock_toolbar_actions(snapper)

    def _restore_native_snap_state(self):
        self.native_snap_locked = False
        self._restore_draft_getpoint_patch()
        self._restore_snapper_patch()

        # Libera primeiro os botoes para o FreeCAD refletir o estado restaurado.
        for _key, item in list(self.native_snap_actions.items()):
            action, checked, enabled = item
            try:
                previous = action.blockSignals(True)
            except Exception:
                previous = None
            try:
                action.setEnabled(bool(enabled))
                if action.isCheckable():
                    action.setChecked(bool(checked))
            except Exception:
                pass
            finally:
                try:
                    action.blockSignals(bool(previous))
                except Exception:
                    pass
        self.native_snap_actions = {}

        state = self.native_snap_state
        self.native_snap_state = None
        if not state:
            return

        snapper = self._get_snapper() or state.get("snapper")
        if snapper is None:
            return

        saved = list(state.get("active_snaps", []) or [])

        # Limpa qualquer modo que tenha escapado durante o bloqueio.
        self._disable_native_modes(snapper)

        toggle = getattr(snapper, "toggle_snap", None)
        if callable(toggle):
            for mode in saved:
                try:
                    toggle(mode, True)
                except Exception:
                    pass
        else:
            try:
                active = getattr(snapper, "active_snaps", None)
                if active is not None:
                    try:
                        active.extend(saved)
                    except Exception:
                        setattr(snapper, "active_snaps", saved)
            except Exception:
                pass

        App.Console.PrintMessage(
            "[Snap Cruzamento Guias] snaps nativos restaurados: {}\n".format(
                ", ".join(str(x) for x in saved) if saved else "nenhum"
            )
        )

    # ----------------------------------------------------
    # VIDA DA FERRAMENTA
    # ----------------------------------------------------

    def start(self):
        if App.ActiveDocument is None:
            raise ValueError("Abra um documento antes de ligar o Snap de Guias.")

        self.doc = App.ActiveDocument
        self.view = Gui.activeDocument().activeView()
        self.scene = self.view.getSceneGraph()

        # O Snap Direct e exclusivo: enquanto estiver ligado, nenhum snap
        # nativo Draft/BIM pode disputar o cursor ou o clique.
        self.native_snap_locked = True
        self._snapshot_native_snap_state()
        self._enforce_native_snap_exclusive()

        self._build_marker()
        self._build_status()
        self.refresh_intersections()
        self._install_callbacks()

        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(REFRESH_MS)
        self.refresh_timer.timeout.connect(self._periodic_refresh)
        self.refresh_timer.start()

        self.native_lock_timer = QtCore.QTimer(self)
        self.native_lock_timer.setInterval(NATIVE_LOCK_MS)
        self.native_lock_timer.timeout.connect(self._enforce_native_snap_exclusive)
        self.native_lock_timer.start()

        self.active = True
        self._enforce_native_snap_exclusive()
        self._set_status(
            f"SNAP GUIAS: EXCLUSIVO | {len(self.intersections)} cruzamento(s) | "
            "snaps nativos bloqueados"
        )

        saved_modes = []
        try:
            saved_modes = list((self.native_snap_state or {}).get("active_snaps", []) or [])
        except Exception:
            pass
        App.Console.PrintMessage(
            f"[Snap Cruzamento Guias] ATIVO EXCLUSIVO — "
            f"{len(self.intersections)} cruzamento(s); snaps nativos bloqueados.\n"
            "[Snap Cruzamento Guias] estado nativo salvo: {}\n".format(
                ", ".join(str(x) for x in saved_modes) if saved_modes else "nenhum"
            )
        )

    def stop(self):
        if not self.active and self.view is None:
            return

        self.active = False

        try:
            if self.refresh_timer is not None:
                self.refresh_timer.stop()
                self.refresh_timer.deleteLater()
        except Exception:
            pass
        self.refresh_timer = None

        try:
            if self.native_lock_timer is not None:
                self.native_lock_timer.stop()
                self.native_lock_timer.deleteLater()
        except Exception:
            pass
        self.native_lock_timer = None

        self._remove_callbacks()
        self._remove_marker()
        self._remove_status()
        self._remove_temp_snap_object()
        self._restore_native_snap_state()

        try:
            self.main_window.statusBar().showMessage(
                "SNAP GUIAS: DESATIVADO", 3000
            )
        except Exception:
            pass

        App.Console.PrintMessage(
            f"[Snap Cruzamento Guias] DESATIVADO.\n"
        )

        self.view = None
        self.scene = None
        self.current_hit = None
        self.pending_hit = None

    # ----------------------------------------------------
    # CRUZAMENTOS
    # ----------------------------------------------------

    def _periodic_refresh(self):
        if not self.active:
            return

        # Garante exclusividade mesmo se o usuario trocar de bancada enquanto
        # o Snap Direct estiver ligado e novas acoes Draft/BIM forem criadas.
        self._enforce_native_snap_exclusive()

        # Se o documento ativo mudou, acompanha o novo documento e viewport.
        if App.ActiveDocument is not self.doc:
            try:
                self._hide_marker()
                self.doc = App.ActiveDocument
                if self.doc is None:
                    self.intersections = []
                    self._set_status("SNAP GUIAS: ATIVO | nenhum documento ativo")
                    return
            except Exception:
                return

        try:
            self.refresh_intersections()
        except Exception:
            pass

    def refresh_intersections(self):
        if self.doc is None:
            self.intersections = []
            return
        self.intersections = capture_intersections(self.doc)

    # ----------------------------------------------------
    # MARCADOR Coin3D
    # ----------------------------------------------------

    def _build_marker(self):
        switch = coin.SoSwitch()
        switch.whichChild = coin.SO_SWITCH_NONE

        root = coin.SoSeparator()

        try:
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            root.addChild(pick)
        except Exception:
            pass

        color = coin.SoBaseColor()
        color.rgb = (1.0, 0.35, 0.0)

        coords = coin.SoCoordinate3()
        coords.point.setNum(1)
        coords.point.set1Value(0, 0.0, 0.0, 0.0)

        # SoMarkerSet possui tamanho de tela praticamente constante e e ideal
        # para indicar um snap sem criar geometria real no documento.
        marker = coin.SoMarkerSet()
        try:
            marker.markerIndex = coin.SoMarkerSet.CROSS_9_9
        except Exception:
            # O indice padrao continua sendo um marcador visivel.
            pass

        root.addChild(color)
        root.addChild(coords)
        root.addChild(marker)
        switch.addChild(root)
        self.scene.addChild(switch)

        self.marker_switch = switch
        self.marker_root = root
        self.marker_coords = coords

    def _remove_marker(self):
        try:
            if self.scene is not None and self.marker_switch is not None:
                self.scene.removeChild(self.marker_switch)
        except Exception:
            pass
        self.marker_switch = None
        self.marker_root = None
        self.marker_coords = None

    def _show_marker(self, point):
        if self.marker_coords is None or self.marker_switch is None:
            return
        self.marker_coords.point.set1Value(
            0, coin.SbVec3f(point.x, point.y, point.z)
        )
        self.marker_switch.whichChild = coin.SO_SWITCH_ALL

    def _hide_marker(self):
        if self.marker_switch is not None:
            self.marker_switch.whichChild = coin.SO_SWITCH_NONE
        self.current_hit = None

    # ----------------------------------------------------
    # STATUS
    # ----------------------------------------------------

    def _build_status(self):
        label = QtWidgets.QLabel()
        label.setObjectName("UhrySnapGuiasStatus")
        label.setMinimumWidth(260)
        label.setToolTip(
            "Snap exclusivo para cruzamentos reais entre Linhas Guia."
        )
        self.main_window.statusBar().addPermanentWidget(label)
        self.status_widget = label
        self.status_label = label

    def _remove_status(self):
        if self.status_widget is None:
            return
        try:
            self.main_window.statusBar().removeWidget(self.status_widget)
        except Exception:
            pass
        try:
            self.status_widget.deleteLater()
        except Exception:
            pass
        self.status_widget = None
        self.status_label = None

    def _set_status(self, text):
        if self.status_label is not None:
            self.status_label.setText(str(text))

    # ----------------------------------------------------
    # CAMERA / DISTANCIA EM TELA
    # ----------------------------------------------------

    def _screen_ray(self, pos):
        x, y = int(pos[0]), int(pos[1])
        p = App.Vector(self.view.getPoint(x, y))

        camera_type = str(self.view.getCameraType())
        if "Perspective" in camera_type:
            cam = self.view.getCameraNode()
            cp = cam.position.getValue()
            origin = vec_from_coin(cp)
            direction = unit(p - origin)
        else:
            origin = p
            direction = unit(
                self.view.getCameraOrientation().multVec(App.Vector(0, 0, -1))
            )

        return origin, direction

    def _world_per_pixel(self, point, pos):
        """Escala aproximada mm/pixel na profundidade do ponto."""
        try:
            size = self.view.getSize()
            height_px = max(1.0, float(size[1]))
            cam = self.view.getCameraNode()
            camera_type = str(self.view.getCameraType())

            if "Perspective" in camera_type:
                cp = vec_from_coin(cam.position.getValue())
                forward = unit(
                    self.view.getCameraOrientation().multVec(App.Vector(0, 0, -1))
                )
                depth = abs((point - cp).dot(forward))
                angle = float(cam.heightAngle.getValue())
                visible_height = 2.0 * max(depth, 1e-6) * math.tan(angle * 0.5)
                return max(visible_height / height_px, 1e-9)

            visible_height = float(cam.height.getValue())
            return max(visible_height / height_px, 1e-9)

        except Exception:
            # Fallback baseado em dois pixels vizinhos no plano de getPoint().
            try:
                x, y = int(pos[0]), int(pos[1])
                a = App.Vector(self.view.getPoint(x, y))
                b = App.Vector(self.view.getPoint(x + 1, y))
                scale = (b - a).Length
                if scale > 1e-9:
                    return scale
            except Exception:
                pass

        return 1.0

    def _screen_point(self, point):
        """Projeta um ponto 3D para pixels da viewport (origem inferior esquerda)."""
        try:
            out = self.view.getPointOnScreen(App.Vector(point))
            return (float(out[0]), float(out[1]))
        except Exception:
            return None

    def _cursor_candidates(self, pos):
        """Converte a posição do evento para os sistemas de pixel usados pela vista.

        FreeCAD/Coin usa origem inferior esquerda. Dependendo do callback e do
        escalonamento HiDPI, a posição pode chegar em pixels lógicos ou físicos.
        Geramos equivalentes e escolhemos a menor distância na tela.
        """
        try:
            mx = float(pos[0])
            my = float(pos[1])
            size = self.view.getSize()
            vw = max(1.0, float(size[0]))
            vh = max(1.0, float(size[1]))
        except Exception:
            return []

        pairs = []

        def add(x, y):
            vals = ((float(x), float(y)), (float(x), vh - float(y)))
            for value in vals:
                if value not in pairs:
                    pairs.append(value)

        # Coordenada Coin direta + Y invertido.
        add(mx, my)

        # Escala entre o viewport Qt (pixels lógicos) e a viewport 3D.
        try:
            graphics = self.view.graphicsView()
            viewport = graphics.viewport() if graphics is not None else None
            if viewport is not None:
                qw = max(1.0, float(viewport.width()))
                qh = max(1.0, float(viewport.height()))
                add(mx * vw / qw, my * vh / qh)

                try:
                    dpr = float(viewport.devicePixelRatioF())
                except Exception:
                    try:
                        dpr = float(viewport.devicePixelRatio())
                    except Exception:
                        dpr = 1.0
                if dpr > 0.0 and abs(dpr - 1.0) > 1.0e-6:
                    add(mx * dpr, my * dpr)
                    add(mx / dpr, my / dpr)
        except Exception:
            pass

        return pairs

    def _nearest_hit(self, pos):
        """Retorna o cruzamento de guia mais próximo do cursor na viewport."""
        if not self.intersections or self.view is None:
            return None

        cursor_positions = self._cursor_candidates(pos)
        if not cursor_positions:
            return None

        best = None
        best_dist2 = None
        radius2 = float(SNAP_RADIUS_PX) ** 2

        for hit in self.intersections:
            screen = self._screen_point(hit["point"])
            if screen is None:
                continue

            sx, sy = screen
            for mx, my in cursor_positions:
                dx = mx - sx
                dy = my - sy
                dist2 = dx * dx + dy * dy
                if dist2 <= radius2 and (best_dist2 is None or dist2 < best_dist2):
                    best = hit
                    best_dist2 = dist2

        return best

    def point_for_screen(self, pos, update_visual=True):
        """Ponto de cruzamento usado pelo Mover por Pontos da Direct."""
        if not self.active:
            return None

        hit = self._nearest_hit(pos)
        self.current_hit = hit

        if hit is None:
            if update_visual:
                self._hide_marker()
                self._set_status(
                    f"SNAP GUIAS: EXCLUSIVO | {len(self.intersections)} cruzamento(s)"
                )
            return None

        point = App.Vector(hit["point"])
        if update_visual:
            self._show_marker(point)
            pair = hit["pairs"][0]
            self._set_status(
                "SNAP GUIAS: CRUZAMENTO | "
                f"{pair[0].Label} x {pair[1].Label}"
            )
        return point

    # ----------------------------------------------------
    # EVENTOS
    # ----------------------------------------------------

    def _install_callbacks(self):
        # Preferimos Pivy porque ele permite marcar o clique como "handled".
        # Assim o FreeCAD nao troca a selecao original da peca ao clicar no snap.
        try:
            self.move_cb = self.view.addEventCallbackPivy(
                coin.SoLocation2Event.getClassTypeId(),
                self._on_move_pivy,
            )
            self.mouse_cb = self.view.addEventCallbackPivy(
                coin.SoMouseButtonEvent.getClassTypeId(),
                self._on_mouse_pivy,
            )
            self.use_pivy = True
            return
        except Exception:
            self.move_cb = None
            self.mouse_cb = None
            self.use_pivy = False

        # Compatibilidade defensiva com builds que nao exponham CallbackPivy.
        self.move_cb = self.view.addEventCallback(
            "SoLocation2Event", self._on_move_dict
        )
        self.mouse_cb = self.view.addEventCallback(
            "SoMouseButtonEvent", self._on_mouse_dict
        )

    def _remove_callbacks(self):
        if self.view is None:
            return

        if self.use_pivy:
            try:
                if self.move_cb is not None:
                    self.view.removeEventCallbackPivy(
                        coin.SoLocation2Event.getClassTypeId(), self.move_cb
                    )
            except Exception:
                pass
            try:
                if self.mouse_cb is not None:
                    self.view.removeEventCallbackPivy(
                        coin.SoMouseButtonEvent.getClassTypeId(), self.mouse_cb
                    )
            except Exception:
                pass
        else:
            try:
                if self.move_cb is not None:
                    self.view.removeEventCallback("SoLocation2Event", self.move_cb)
            except Exception:
                pass
            try:
                if self.mouse_cb is not None:
                    self.view.removeEventCallback("SoMouseButtonEvent", self.mouse_cb)
            except Exception:
                pass

        self.move_cb = None
        self.mouse_cb = None

    def _draft_command_active(self):
        try:
            return getattr(App, "activeDraftCommand", None) is not None
        except Exception:
            return False

    def _handle_move(self, pos):
        if not self.active:
            return

        point = self.point_for_screen(pos, update_visual=True)
        if point is None:
            return

        hit = self.current_hit
        if hit is None:
            return
        pair = hit["pairs"][0]
        suffix = (
            "captura ativa no comando atual"
            if self._draft_command_active()
            else "clique para travar"
        )
        self._set_status(
            "SNAP GUIAS: CRUZAMENTO | "
            f"{pair[0].Label} x {pair[1].Label} | {suffix}"
        )

    def _request_lock(self, event_callback=None):
        if self.current_hit is None:
            return False

        # Durante um comando Draft (Mover por Pontos, Linha, etc.) o clique deve
        # continuar pertencendo ao comando ativo. O cruzamento ja foi injetado
        # diretamente em Gui.Snapper.snap pelo wrapper acima.
        if self._draft_command_active():
            return False

        # O snap e destino da operacao Ponto->Ponto, portanto a origem precisa
        # estar selecionada ANTES do clique no cruzamento.
        if not valid_origin_selection():
            self._set_status(
                "SNAP GUIAS: selecione primeiro UMA referencia da peca; "
                "depois clique no cruzamento"
            )
            try:
                if event_callback is not None:
                    event_callback.setHandled()
            except Exception:
                pass
            return True

        self.pending_hit = {
            "point": App.Vector(self.current_hit["point"]),
            "pairs": list(self.current_hit["pairs"]),
        }

        # Impede o clique de selecionar uma linha/face que esteja atras do marcador.
        try:
            if event_callback is not None:
                event_callback.setHandled()
        except Exception:
            pass

        # Alterar documento/selection fora do callback Coin3D e mais seguro.
        QtCore.QTimer.singleShot(0, self._lock_deferred)
        return True

    def _on_move_pivy(self, cb):
        try:
            event = cb.getEvent()
            pos = event.getPosition()
            self._handle_move((int(pos[0]), int(pos[1])))
        except Exception:
            pass

    def _on_mouse_pivy(self, cb):
        if not self.active or self.current_hit is None:
            return
        try:
            event = cb.getEvent()
            if (
                event.getButton() == coin.SoMouseButtonEvent.BUTTON1
                and event.getState() == coin.SoButtonEvent.DOWN
            ):
                self._request_lock(cb)
        except Exception:
            pass

    def _on_move_dict(self, info):
        pos = info.get("Position")
        if pos:
            self._handle_move(pos)

    def _on_mouse_dict(self, info):
        if not self.active or self.current_hit is None:
            return
        if str(info.get("State", "")).upper() != "DOWN":
            return
        button = str(info.get("Button", "")).upper()
        if button in ("BUTTON1", "LEFT", "LEFTBUTTON"):
            # Nesta compatibilidade antiga nao podemos consumir o evento.
            # A selecao sera corrigida no ciclo Qt seguinte apenas se necessario.
            self._request_lock(None)

    # ----------------------------------------------------
    # PONTO TEMPORARIO / SELECAO
    # ----------------------------------------------------

    def _get_or_create_snap_object(self):
        if self.doc is None:
            raise ValueError("Documento nao disponivel.")

        obj = self.doc.getObject(SNAP_OBJECT_NAME)
        if obj is None:
            obj = self.doc.addObject("Part::Feature", SNAP_OBJECT_NAME)
            obj.Label = SNAP_OBJECT_LABEL
            try:
                obj.addProperty(
                    "App::PropertyBool",
                    "UhrySnapTemporario",
                    "Uhry",
                    "Ponto temporario criado pelo Snap Cruzamento de Guias.",
                )
                obj.UhrySnapTemporario = True
                obj.setEditorMode("UhrySnapTemporario", 1)
            except Exception:
                pass

            try:
                obj.ViewObject.PointSize = 8.0
                obj.ViewObject.PointColor = (1.0, 0.35, 0.0)
            except Exception:
                pass

        return obj

    def _lock_deferred(self):
        if self.pending_hit is None or self.doc is None:
            return

        try:
            # Com CallbackPivy a selecao original permanece intacta.
            # Se a seleção tiver sido alterada pelo clique normal,
            # avisamos em vez de tentar adivinhar uma origem perdida.
            if not valid_origin_selection():
                self._set_status(
                    "SNAP GUIAS: a selecao de origem mudou; selecione novamente "
                    "a referencia da peca e clique no cruzamento"
                )
                self.pending_hit = None
                return

            p = App.Vector(self.pending_hit["point"])
            obj = self._get_or_create_snap_object()
            obj.Shape = Part.Vertex(p)
            self.doc.recompute()

            # Adiciona como SEGUNDA selecao, preservando a primeira exatamente.
            Gui.Selection.addSelection(obj, "Vertex1")

            pair = self.pending_hit["pairs"][0]
            self._set_status(
                "SNAP GUIAS: DESTINO TRAVADO | "
                f"{pair[0].Label} x {pair[1].Label} | execute Posicionar Peca"
            )

            App.Console.PrintMessage(
                "\n====================================\n"
                "SNAP CRUZAMENTO GUIAS\n"
                "====================================\n"
                f"Guia 1: {pair[0].Label}\n"
                f"Guia 2: {pair[1].Label}\n"
                f"Ponto: ({p.x:.6f}, {p.y:.6f}, {p.z:.6f})\n"
                "Destino adicionado como segunda selecao.\n"
                "====================================\n"
            )

        except Exception as exc:
            self._set_status(f"SNAP GUIAS: erro ao travar ponto — {exc}")
            App.Console.PrintError(
                f"[Snap Cruzamento Guias] erro: {exc}\n"
            )
            App.Console.PrintError(traceback.format_exc())
        finally:
            self.pending_hit = None

    def _remove_temp_snap_object(self):
        doc = self.doc if self.doc is not None else App.ActiveDocument
        if doc is None:
            return
        try:
            obj = doc.getObject(SNAP_OBJECT_NAME)
            if obj is not None:
                doc.removeObject(obj.Name)
                doc.recompute()
        except Exception:
            pass


# ============================================================
# TOGGLE
# ============================================================

def _remove_controller_attr(main):
    try:
        delattr(main, CONTROLLER_ATTR)
    except Exception:
        try:
            setattr(main, CONTROLLER_ATTR, None)
        except Exception:
            pass


def _action_matches_snap(action):
    try:
        name = str(action.objectName() or "")
    except Exception:
        name = ""
    try:
        text = str(action.text() or "").replace("&", "").strip()
    except Exception:
        text = ""
    return name == COMMAND_ID or text == "Snap Cruzamento de Guias"


def force_ui_unchecked():
    """Mantém o botão visualmente desligado quando não existe controlador ativo."""
    if is_active():
        return False
    try:
        main = Gui.getMainWindow()
        action_type = getattr(QtWidgets, "QAction", None)
        if action_type is None:
            action_type = getattr(QtGui, "QAction", None)
        if action_type is None:
            return False

        for action in main.findChildren(action_type):
            if not _action_matches_snap(action):
                continue
            try:
                previous = action.blockSignals(True)
            except Exception:
                previous = None
            try:
                if action.isCheckable():
                    action.setChecked(False)
            except Exception:
                pass
            finally:
                try:
                    action.blockSignals(bool(previous))
                except Exception:
                    pass
        return True
    except Exception:
        return False


def schedule_force_ui_unchecked():
    force_ui_unchecked()
    try:
        QtCore.QTimer.singleShot(0, force_ui_unchecked)
        QtCore.QTimer.singleShot(150, force_ui_unchecked)
        QtCore.QTimer.singleShot(500, force_ui_unchecked)
    except Exception:
        pass


def active_controller():
    try:
        controller = getattr(Gui.getMainWindow(), CONTROLLER_ATTR, None)
        if controller is not None and bool(getattr(controller, "active", False)):
            return controller
    except Exception:
        pass
    return None


def point_for_screen(pos, update_visual=True):
    controller = active_controller()
    if controller is None:
        return None
    try:
        return controller.point_for_screen(pos, update_visual=update_visual)
    except Exception:
        return None


def reset_runtime_state():
    """Garante que o Snap Direct sempre inicia desligado.

    É chamado uma única vez ao inicializar a bancada. Também limpa um
    controlador deixado em memória quando a bancada é recarregada durante
    desenvolvimento, restaurando os snaps nativos antes de continuar.
    """
    try:
        main = Gui.getMainWindow()
        existing = getattr(main, CONTROLLER_ATTR, None)
        if existing is not None:
            try:
                existing.stop()
            except Exception:
                pass
        _remove_controller_attr(main)
        force_ui_unchecked()
        try:
            Gui.updateCommands()
        except Exception:
            pass
        schedule_force_ui_unchecked()
        return True
    except Exception:
        return False


def set_enabled(enabled):
    """Liga/desliga explicitamente o Snap Direct.

    Comandos checkable do FreeCAD chamam Activated(index), onde o indice
    representa o estado do botao. Trabalhar com estado explicito evita um
    segundo toggle acidental e permite o uso durante comandos Draft ativos.
    """
    main = Gui.getMainWindow()
    existing = getattr(main, CONTROLLER_ATTR, None)
    want_on = bool(enabled)

    if want_on:
        if existing is not None and bool(getattr(existing, "active", False)):
            return True

        # Limpa um controlador incompleto deixado por uma falha anterior.
        if existing is not None:
            try:
                existing.stop()
            except Exception:
                pass
            _remove_controller_attr(main)

        controller = SnapGuideIntersections()
        setattr(main, CONTROLLER_ATTR, controller)
        try:
            controller.start()
            return True
        except Exception:
            try:
                controller.stop()
            except Exception:
                pass
            _remove_controller_attr(main)
            raise

    # want_off
    if existing is not None:
        try:
            existing.stop()
        finally:
            _remove_controller_attr(main)
    schedule_force_ui_unchecked()
    return True


def toggle():
    return set_enabled(not is_active())


def is_active():
    """True quando o Snap Cruzamento de Guias esta ligado."""
    try:
        existing = getattr(Gui.getMainWindow(), CONTROLLER_ATTR, None)
        return existing is not None and bool(getattr(existing, "active", False))
    except Exception:
        return False


def run_command(desired_state=None):
    """Entrada da bancada Direct.

    ``desired_state`` e fornecido pelo FreeCAD para comandos checkable
    (0 = desligado, 1 = ligado). Quando nao houver argumento, alterna o estado.
    """
    try:
        if desired_state is None:
            toggle()
        else:
            set_enabled(bool(desired_state))

        try:
            Gui.updateCommands()
        except Exception:
            pass
        return True
    except Exception as exc:
        App.Console.PrintError(
            f"[Snap Cruzamento Guias] {exc}\n"
        )
        App.Console.PrintError(traceback.format_exc())
        try:
            QtWidgets.QMessageBox.critical(
                Gui.getMainWindow(),
                "Snap Cruzamento Guias",
                str(exc),
            )
        except Exception:
            pass
        return False

