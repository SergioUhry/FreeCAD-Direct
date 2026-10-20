# -*- coding: utf-8 -*-
"""Base associativa: conserva o objeto fonte, suas expressões e seu histórico."""
import FreeCAD as App

DIMENSIONS = ('Length', 'Width', 'Height', 'Radius', 'Radius1', 'Radius2',
              'Radius3', 'Angle', 'Angle1', 'Angle2', 'Angle3')


class ParametricBase:
    def __init__(self, obj, source):
        obj.addProperty('App::PropertyLink', 'Source', 'Direct',
                        'Objeto original editável; expandir Base_Direct na árvore.')
        obj.Source = source
        obj.setEditorMode('Source', 1)
        obj.Proxy = self
        self.sync_dimensions(obj)

    def sync_dimensions(self, obj):
        source = getattr(obj, 'Source', None)
        if source is None:
            return
        self._syncing = True
        try:
            expressions = dict(getattr(source, 'ExpressionEngine', []))
            for name in DIMENSIONS:
                if name not in source.PropertiesList:
                    continue
                kind = source.getTypeIdOfProperty(name)
                if kind not in ('App::PropertyLength', 'App::PropertyDistance',
                                'App::PropertyAngle', 'App::PropertyFloat',
                                'App::PropertyFloatConstraint'):
                    continue
                if name not in obj.PropertiesList:
                    # FloatConstraint requer uma tupla de limites, não um número.
                    mirror_kind = 'App::PropertyFloat' if kind == 'App::PropertyFloatConstraint' else kind
                    obj.addProperty(mirror_kind, name, 'Dimensões da fonte',
                                    'Edita a dimensão correspondente no objeto original.')
                value = getattr(source, name)
                if getattr(obj, name) != value:
                    setattr(obj, name, value)
                obj.setEditorMode(name, 1 if name in expressions else 0)
        finally:
            self._syncing = False

    def onChanged(self, obj, prop):
        if getattr(self, '_syncing', False) or prop not in DIMENSIONS:
            return
        source = getattr(obj, 'Source', None)
        if source is None or prop not in source.PropertiesList:
            return
        if prop in dict(getattr(source, 'ExpressionEngine', [])):
            self.sync_dimensions(obj)
            return
        setattr(source, prop, getattr(obj, prop))

    def onDocumentRestored(self, obj):
        self.sync_dimensions(obj)

    def execute(self, obj):
        source = obj.Source
        if source is None or source.Shape.isNull():
            raise RuntimeError('A fonte da Base_Direct está ausente ou sem geometria.')
        self.sync_dimensions(obj)
        shape = source.Shape.copy()
        # A transformação original fica no Body. A base trabalha em seu plano local.
        shape.Placement = App.Placement()
        obj.Shape = shape

    def dumps(self):
        return None

    def loads(self, state):
        pass


class ViewProviderParametricBase:
    def __init__(self, view):
        self.Object = view.Object
        view.Proxy = self

    def attach(self, view):
        self.Object = view.Object

    def claimChildren(self):
        source = getattr(self.Object, 'Source', None)
        return [source] if source is not None else []

    def doubleClicked(self, view):
        import FreeCADGui as Gui
        source = getattr(view.Object, 'Source', None)
        if source is None:
            return False
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(source)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        pass


def create_base(body, source, copy_appearance):
    base = body.newObject('PartDesign::FeaturePython', 'Base_Direct')
    base.Label = 'Base_Direct'
    ParametricBase(base, source)
    ViewProviderParametricBase(base.ViewObject)
    base.Proxy.execute(base)
    copy_appearance(source, base)
    source.Visibility = False
    body.Tip = base
    return base
