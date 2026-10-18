# -*- coding: utf-8 -*-
from draftguitools import gui_trackers as trackers

class GhostPreview:
    def __init__(self, objects, parent_places=None):
        self.tracker = trackers.ghostTracker(objects, parent_places=parent_places)
        self.tracker.on()
    def move(self, delta):
        self.tracker.move(delta)
    def rotate(self, axis, angle_radians):
        self.tracker.rotate(axis, angle_radians)
    def center(self, point):
        self.tracker.center(point)
    def finish(self):
        if self.tracker is not None:
            self.tracker.finalize()
            self.tracker = None
