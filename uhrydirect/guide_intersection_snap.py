# -*- coding: utf-8 -*-
"""Snap para cruzamentos reais entre Linhas Guia.

Considera apenas interseções coplanares em 3D e preserva a seleção usada
pelas ferramentas de posicionamento.
"""

import math
import traceback

import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtWidgets
    except ImportError:
        from PySide6 import QtCore, QtWidgets


GUIDE_FLAG = "UhryGuiaReferencia"
DIRECT_GUIDE_FLAG = "DirectGuiaReferencia"
CONTROLLER_ATTR = "_uhry_snap_cruzamento_guias_controller"
SNAP_OBJECT_NAME = "UhrySnapCruzamento"
SNAP_OBJECT_LABEL = "Snap Cruzamento Guias"

# Tolerancias geometricas em mm.
COPLANAR_TOL_MM = 0.05
SEGMENT_TOL_MM = 0.20
DUPLICATE_TOL_MM = 0.05
PARALLEL_EPS = 1e-12

# Raio de captura em pixels na tela.
SNAP_RADIUS_PX = 14.0

# Atualizacao periodica dos cruzamentos. Nao faz recompute no documento.
REFRESH_MS = 700


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

        self.use_pivy = False
        self.move_cb = None
        self.mouse_cb = None

    # ----------------------------------------------------
    # VIDA DA FERRAMENTA
    # ----------------------------------------------------

    def start(self):
        if App.ActiveDocument is None:
            raise ValueError("Abra um documento antes de ligar o Snap de Guias.")

        self.doc = App.ActiveDocument
        self.view = Gui.activeDocument().activeView()
        self.scene = self.view.getSceneGraph()

        self._build_marker()
        self._build_status()
        self.refresh_intersections()
        self._install_callbacks()

        self.refresh_timer = QtCore.QTimer(self)
        self.refresh_timer.setInterval(REFRESH_MS)
        self.refresh_timer.timeout.connect(self._periodic_refresh)
        self.refresh_timer.start()

        self.active = True
        self._set_status(
            f"SNAP GUIAS: ATIVO | {len(self.intersections)} cruzamento(s) | "
            "selecione 1 referencia da peca e clique no cruzamento"
        )

        App.Console.PrintMessage(
            f"[Snap Cruzamento Guias] ATIVO — "
            f"{len(self.intersections)} cruzamento(s).\n"
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

        self._remove_callbacks()
        self._remove_marker()
        self._remove_status()
        self._remove_temp_snap_object()

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

    def _nearest_hit(self, pos):
        if not self.intersections:
            return None

        try:
            origin, direction = self._screen_ray(pos)
        except Exception:
            return None

        best = None
        best_ratio = None

        for hit in self.intersections:
            p = hit["point"]
            t = (p - origin).dot(direction)

            # Em perspectiva, pontos atras da camera nao podem ser candidatos.
            if "Perspective" in str(self.view.getCameraType()) and t <= 0:
                continue

            closest = origin + direction * t
            dist_world = (p - closest).Length
            world_per_px = self._world_per_pixel(p, pos)
            radius_world = max(world_per_px * SNAP_RADIUS_PX, 0.05)
            ratio = dist_world / radius_world

            if ratio <= 1.0 and (best_ratio is None or ratio < best_ratio):
                best = hit
                best_ratio = ratio

        return best

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

    def _handle_move(self, pos):
        if not self.active:
            return

        hit = self._nearest_hit(pos)
        self.current_hit = hit

        if hit is None:
            self._hide_marker()
            self._set_status(
                f"SNAP GUIAS: ATIVO | {len(self.intersections)} cruzamento(s)"
            )
            return

        self._show_marker(hit["point"])
        pair = hit["pairs"][0]
        self._set_status(
            "SNAP GUIAS: CRUZAMENTO | "
            f"{pair[0].Label} x {pair[1].Label} | clique para travar"
        )

    def _request_lock(self, event_callback=None):
        if self.current_hit is None:
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

def toggle():
    main = Gui.getMainWindow()
    existing = getattr(main, CONTROLLER_ATTR, None)

    if existing is not None:
        try:
            existing.stop()
        finally:
            try:
                delattr(main, CONTROLLER_ATTR)
            except Exception:
                setattr(main, CONTROLLER_ATTR, None)
        return

    controller = SnapGuideIntersections()
    setattr(main, CONTROLLER_ATTR, controller)
    try:
        controller.start()
    except Exception:
        try:
            controller.stop()
        except Exception:
            pass
        try:
            delattr(main, CONTROLLER_ATTR)
        except Exception:
            pass
        raise




def is_active():
    """True quando o Snap Cruzamento de Guias esta ligado."""
    try:
        existing = getattr(Gui.getMainWindow(), CONTROLLER_ATTR, None)
        return existing is not None and bool(getattr(existing, "active", False))
    except Exception:
        return False


def run_command():
    """Entrada da bancada Direct: alterna LIGADO/DESLIGADO com dialogo de erro."""
    try:
        toggle()
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
