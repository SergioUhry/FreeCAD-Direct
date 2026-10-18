# -*- coding: utf-8 -*-
import FreeCAD as App

class NumericInputController:
    @staticmethod
    def parse_length(text):
        text = str(text).strip()
        if not text:
            return None
        try:
            return float(text.replace(",", "."))
        except Exception:
            q = App.Units.Quantity(text)
            return q.getValueAs("mm").Value

    @staticmethod
    def parse_angle(text):
        text = str(text).strip()
        if not text:
            return None
        try:
            return float(text.replace(",", "."))
        except Exception:
            q = App.Units.Quantity(text)
            return q.getValueAs("deg").Value
