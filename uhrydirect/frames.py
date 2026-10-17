# -*- coding: utf-8 -*-
import FreeCAD as App

class ReferenceFrame:
    def __init__(self, placement=None):
        self.placement = App.Placement(placement or App.Placement())
    def to_world(self, p):
        return self.placement.multVec(App.Vector(p))
    def to_local(self, p):
        return self.placement.inverse().multVec(App.Vector(p))
    def axis_x(self):
        return self.placement.Rotation.multVec(App.Vector(1, 0, 0))
    def axis_y(self):
        return self.placement.Rotation.multVec(App.Vector(0, 1, 0))
    def axis_z(self):
        return self.placement.Rotation.multVec(App.Vector(0, 0, 1))
