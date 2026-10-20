# -*- coding: utf-8 -*-
"""Painel de Parâmetros para a bancada Direct — teste 0.1.2."""
import json, re, unicodedata, traceback, os
import FreeCAD as App
import FreeCADGui as Gui
try:
    from PySide2 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui

TYPES={'Comprimento (mm)':'App::PropertyLength','Ângulo (graus)':'App::PropertyAngle','Número':'App::PropertyFloat'}
_PANEL=None; _DOCK=None; _OBS=None; _FILTER=None; _TIMER=None; _ACTION=None

def metadata(o):
    try: return json.loads(o.UhryParametrosJSON or '{}')
    except Exception: return {}
def sets(doc): return [o for o in doc.Objects if 'UhryParametrosJSON' in o.PropertiesList]
def expr(o,p):
    try: return next((str(e) for q,e in o.ExpressionEngine if q==p),'')
    except Exception: return ''
def refs(doc):
    r={}
    for o in sets(doc):
        owner=doc.getObject(o.UhryEscopo); label=(owner.Label+' ['+owner.Name+']') if owner else 'Projeto'
        for p,i in metadata(o).items(): r[label+' / '+i['name']]=o.Name+'.'+p
    return r

def internal_name(name,obj,current=None):
    raw=unicodedata.normalize('NFKD',name).encode('ascii','ignore').decode('ascii')
    parts=re.findall(r'[A-Za-z0-9]+',raw); base=''.join(x[:1].upper()+x[1:] for x in parts) or 'Parametro'
    if base[0].isdigit(): base='P'+base
    reserved={'Label','Label2','ExpressionEngine','Placement','Proxy','ViewObject','Document','Name','State'}
    if base in reserved: base='Param'+base
    candidate=base; n=2
    while candidate in obj.PropertiesList and candidate!=current:
        candidate=base+str(n); n+=1
    return candidate

def sketch_constraint_is_driving(obj,index,constraint=None):
    if constraint is not None:
        for attr_name in ('isDriving','Driving'):
            try:
                attr=getattr(constraint,attr_name); return bool(attr() if callable(attr) else attr)
            except Exception: pass
    try:
        result=obj.getDriving(index)
        if isinstance(result,(tuple,list)):
            for item in reversed(result):
                if isinstance(item,bool): return item
        return bool(result)
    except Exception: pass
    try: return bool(obj.isDriving(index))
    except Exception: return True

def compatible_expression_properties(o):
    result=[]
    accepted={'App::PropertyLength','App::PropertyDistance','App::PropertyAngle','App::PropertyFloat','App::PropertyInteger','App::PropertyQuantity','App::PropertyLengthConstraint','App::PropertyAngleConstraint','App::PropertyIntegerConstraint','App::PropertyFloatConstraint'}
    common={'Length':'Comprimento (Length)','Width':'Largura (Width)','Height':'Altura (Height)','Radius':'Raio (Radius)','Diameter':'Diâmetro (Diameter)','Angle':'Ângulo (Angle)','LengthFwd':'Comprimento frontal (LengthFwd)','LengthRev':'Comprimento reverso (LengthRev)','Length2':'Comprimento 2 (Length2)','Offset':'Deslocamento (Offset)','Distance':'Distância (Distance)'}
    for prop in getattr(o,'PropertiesList',[]):
        try: ptype=o.getTypeIdOfProperty(prop)
        except Exception: continue
        compatible=(ptype in accepted or any(k in str(ptype) for k in ('PropertyLength','PropertyDistance','PropertyAngle','PropertyFloat','PropertyInteger','PropertyQuantity')))
        if not compatible: continue
        try: mode=o.getEditorMode(prop)
        except Exception: mode=0
        if mode==2: continue
        result.append((common.get(prop,prop),prop,ptype))
    return result

def property_paths(o):
    out=[]
    if hasattr(o,'Constraints'):
        allowed={'Distance','DistanceX','DistanceY','Radius','Diameter','Angle','AngleViaPoint'}
        try: constraints=list(o.Constraints)
        except Exception: constraints=[]
        for i,c in enumerate(constraints):
            if getattr(c,'Type','') in allowed and sketch_constraint_is_driving(o,i,c):
                name=getattr(c,'Name','') or ('Cota %d (%s)'%(i+1,c.Type)); out.append(('Sketch: '+name,'Constraints[%d]'%i))
    for label,path,_ptype in compatible_expression_properties(o): out.append((label,path))
    if 'Placement' in getattr(o,'PropertiesList',[]): out += [('Posição X','Placement.Base.x'),('Posição Y','Placement.Base.y'),('Posição Z','Placement.Base.z')]
    return out

class Panel(QtWidgets.QWidget):
    def __init__(self,doc):
        super().__init__(); self.doc=doc; self.current=None; self.targets=[]
        lay=QtWidgets.QVBoxLayout(self)
        self.scope=QtWidgets.QComboBox(); lay.addWidget(QtWidgets.QLabel('Escopo das variáveis:')); lay.addWidget(self.scope)
        self.params=QtWidgets.QComboBox(); lay.addWidget(self.params)
        form=QtWidgets.QFormLayout(); lay.addLayout(form)
        self.name=QtWidgets.QLineEdit(); form.addRow('Nome do parâmetro:',self.name)
        self.kind=QtWidgets.QComboBox(); self.kind.addItems(list(TYPES)); form.addRow('Tipo:',self.kind)
        self.value=QtWidgets.QDoubleSpinBox(); self.value.setRange(-1e9,1e9); self.value.setDecimals(4); form.addRow('Valor:',self.value)
        self.formula=QtWidgets.QLineEdit(); self.formula.setPlaceholderText('Ex.: {Projeto / Largura} - 2 * 5mm'); form.addRow('Fórmula:',self.formula)
        self.ref=QtWidgets.QComboBox(); form.addRow('Parâmetro para inserir:',self.ref)
        b=QtWidgets.QPushButton('Inserir parâmetro na fórmula'); b.clicked.connect(self.insert_ref); form.addRow(b)
        save=QtWidgets.QPushButton('Salvar parâmetro e recalcular'); save.clicked.connect(self.save_param); form.addRow(save)
        self.status=QtWidgets.QLabel(); self.status.setWordWrap(True); form.addRow(self.status)
        g=QtWidgets.QGroupBox('Vincular a uma medida do 3D'); gl=QtWidgets.QFormLayout(g); lay.addWidget(g)
        self.target=QtWidgets.QComboBox(); gl.addRow('Objeto / Sketch:',self.target)
        self.path=QtWidgets.QComboBox(); self.path.setEditable(True); self.path.setInsertPolicy(QtWidgets.QComboBox.NoInsert); gl.addRow('Medida:',self.path)
        try: self.path.lineEdit().setPlaceholderText('Escolha a medida ou digite a propriedade')
        except Exception: pass
        bind=QtWidgets.QPushButton('Vincular medida ao parâmetro'); bind.clicked.connect(self.bind); gl.addRow(bind)
        self.info=QtWidgets.QLabel(); self.info.setWordWrap(True); gl.addRow(self.info)
        self.scope.currentIndexChanged.connect(self.reload_params); self.params.currentIndexChanged.connect(self.load_param); self.target.currentIndexChanged.connect(self.target_changed); self.path.currentIndexChanged.connect(self.show_existing)
        self.reload_all()
    def reload_all(self):
        cur=self.scope.currentData() if self.scope.count() else ''
        self.scope.blockSignals(True); self.scope.clear(); self.scope.addItem('Projeto inteiro','')
        for o in self.doc.Objects:
            if o.TypeId in ('App::Part','PartDesign::Body'): self.scope.addItem(('Conjunto: ' if o.TypeId=='App::Part' else 'Peça: ')+o.Label+' ['+o.Name+']',o.Name)
        i=self.scope.findData(cur); self.scope.setCurrentIndex(i if i>=0 else 0); self.scope.blockSignals(False); self.reload_targets(); self.reload_params()
    def scope_set(self): return next((o for o in sets(self.doc) if o.UhryEscopo==(self.scope.currentData() or '')),None)
    def reload_params(self,*a):
        self.params.blockSignals(True); self.params.clear(); self.params.addItem('Criar Novo Parâmetro...',None)
        o=self.scope_set()
        if o:
            for p,d in metadata(o).items(): self.params.addItem(d.get('name',p),p)
        self.params.blockSignals(False); self._refs=refs(self.doc); self.ref.clear(); self.ref.addItems(sorted(self._refs)); self.load_param()
    def load_param(self,*a):
        o=self.scope_set(); p=self.params.currentData(); self.current=(o,p) if o and p else None; self.kind.setEnabled(self.current is None)
        if self.current:
            d=metadata(o)[p]; self.name.setText(d['name']); self.kind.setCurrentText(d['kind']); v=getattr(o,p); self.value.setValue(float(v.Value if hasattr(v,'Value') else v)); self.formula.setText(self.friendly(expr(o,p))); self.status.setText('<b>Referência FreeCAD:</b> %s.%s'%(o.Name,p))
        else: self.name.clear(); self.formula.clear(); self.value.setValue(0); self.status.setText('Pronto para novo parâmetro.')
    def friendly(self,t):
        for label,ref in sorted(self._refs.items(),key=lambda x:len(x[1]),reverse=True): t=re.sub(r'(?<![A-Za-z0-9_])'+re.escape(ref)+r'(?![A-Za-z0-9_])','{'+label+'}',t)
        return t
    def compile_formula(self,t):
        def rr(m):
            k=m.group(1)
            if k not in self._refs: raise ValueError('Parâmetro não encontrado: '+k)
            return self._refs[k]
        return re.sub(r'\{([^{}]+)\}',rr,t)
    def insert_ref(self):
        if self.ref.currentText(): self.formula.insert('{'+self.ref.currentText()+'}')
    def save_param(self):
        try:
            name=self.name.text().strip()
            if not name: raise ValueError('Informe o nome do parâmetro.')
            o=self.scope_set(); data=metadata(o) if o else {}; p=self.current[1] if self.current else None; formula=self.compile_formula(self.formula.text().strip())
            self.doc.openTransaction('Parâmetro Direct')
            if o is None:
                o=self.doc.addObject('App::VarSet','ParametrosUhry'); o.addProperty('App::PropertyString','UhryEscopo','Uhry'); o.addProperty('App::PropertyString','UhryParametrosJSON','Uhry'); o.UhryEscopo=self.scope.currentData() or ''; o.Label='Parâmetros — '+self.scope.currentText(); o.setEditorMode('UhryEscopo',2); o.setEditorMode('UhryParametrosJSON',2)
            if p is None: p=internal_name(name,o); o.addProperty(TYPES[self.kind.currentText()],p,'Parâmetros',name)
            o.setExpression(p,None)
            if formula: o.setExpression(p,formula)
            else: setattr(o,p,self.value.value())
            data[p]={'name':name,'kind':self.kind.currentText()}; o.UhryParametrosJSON=json.dumps(data,ensure_ascii=False); self.doc.recompute(); self.doc.commitTransaction(); self.reload_all(); self.params.setCurrentIndex(self.params.findData(p))
        except Exception as e:
            try: self.doc.abortTransaction()
            except Exception: pass
            QtWidgets.QMessageBox.critical(self,'Direct — Parâmetros',str(e))
    def reload_targets(self):
        cur=self.target.currentData() if self.target.count() else None; self.target.blockSignals(True); self.target.clear(); self.targets=[]
        for o in self.doc.Objects:
            if o.TypeId=='App::VarSet': continue
            self.targets.append(o); self.target.addItem(o.Label+' ['+o.Name+']',o.Name)
        i=self.target.findData(cur); self.target.setCurrentIndex(i if i>=0 else (0 if self.target.count() else -1)); self.target.blockSignals(False); self.target_changed()
    def target_obj(self):
        n=self.target.currentData(); return self.doc.getObject(n) if n else None
    def selected_path(self):
        data=self.path.currentData(); return str(data) if data else self.path.currentText().strip()
    def target_changed(self,*a):
        o=self.target_obj(); old=self.selected_path() if self.path.count() else ''; self.path.blockSignals(True); self.path.clear()
        if not o:
            self.path.blockSignals(False); self.info.setText('Nenhum objeto selecionado.'); return
        paths=property_paths(o)
        for label,p in paths: self.path.addItem(label,p)
        self.path.blockSignals(False)
        if old:
            j=self.path.findData(old)
            if j<0: j=self.path.findText(old)
            if j>=0: self.path.setCurrentIndex(j)
        if self.path.count() and self.path.currentIndex()<0: self.path.setCurrentIndex(0)
        self.info.setText('<b>Objeto:</b> %s &nbsp; <b>Tipo:</b> %s &nbsp; <b>Medidas encontradas:</b> %d'%(o.Label,o.TypeId,len(paths))); self.show_existing()
    def show_existing(self,*a):
        o=self.target_obj(); p=self.selected_path()
        base=re.sub(r'<br><b>Expressão atual:</b>.*$','',self.info.text())
        if o is not None and p: self.info.setText(base+'<br><b>Expressão atual:</b> '+(expr(o,p) or 'valor direto manual'))
    def _suggest_axis_dimension(self,o,sub):
        if not sub: return None
        available={self.path.itemData(i):i for i in range(self.path.count())}; axis=None; shape=getattr(o,'Shape',None); tol=1e-7
        try:
            if shape is not None and sub.startswith('Edge'):
                n=int(sub[4:])-1
                if 0<=n<len(shape.Edges):
                    bb=shape.Edges[n].BoundBox; spans={'X':bb.XLength,'Y':bb.YLength,'Z':bb.ZLength}
                    if max(spans.values())>tol: axis=max(spans,key=spans.get)
            elif shape is not None and sub.startswith('Face'):
                n=int(sub[4:])-1
                if 0<=n<len(shape.Faces):
                    bb=shape.Faces[n].BoundBox; spans={'X':bb.XLength,'Y':bb.YLength,'Z':bb.ZLength}; axis=min(spans,key=spans.get)
        except Exception: axis=None
        if not axis: return None
        candidates={'X':['Length','LengthFwd','Length2'],'Y':['Width'],'Z':['Height']}
        for prop in candidates.get(axis,[]):
            if prop in available: return prop
        return None
    def follow_selection(self,o,sub=''):
        if o is None or o.Document!=self.doc or o.TypeId=='App::VarSet': return
        i=self.target.findData(o.Name)
        if i<0: self.reload_targets(); i=self.target.findData(o.Name)
        if i>=0: self.target.setCurrentIndex(i); self.target_changed()
        suggested=self._suggest_axis_dimension(o,sub)
        if suggested:
            j=self.path.findData(suggested)
            if j>=0:
                self.path.setCurrentIndex(j); self.show_existing(); self.info.setText(self.info.text()+'<br><b>Seleção 3D:</b> %s → <b>%s</b>'%(sub,self.path.currentText())); return
        if sub: self.info.setText(self.info.text()+'<br><b>Seleção 3D:</b> '+str(sub))
    def bind(self):
        try:
            if not self.current: raise ValueError('Selecione um parâmetro salvo.')
            o=self.target_obj(); pth=self.selected_path()
            if o is None or not pth: raise ValueError('Selecione objeto e medida.')
            ps,pp=self.current; self.doc.openTransaction('Vincular parâmetro Direct'); o.setExpression(pth,ps.Name+'.'+pp); self.doc.recompute(); self.doc.commitTransaction(); self.status.setText('Vínculo aplicado: %s → %s.%s'%(pth,ps.Name,pp)); self.show_existing()
        except Exception as e:
            try: self.doc.abortTransaction()
            except Exception: pass
            QtWidgets.QMessageBox.critical(self,'Direct — Parâmetros',str(e))

class Obs:
    def addSelection(self,d,o,s,p):
        if _PANEL and _PANEL.doc.Name==d:
            obj=_PANEL.doc.getObject(o); QtCore.QTimer.singleShot(0,lambda:_PANEL.follow_selection(obj,s))
    def setSelection(self,d):
        try:
            if not _PANEL or _PANEL.doc.Name!=d: return
            sel=Gui.Selection.getSelectionEx(d)
            if sel:
                item=sel[-1]; sub=item.SubElementNames[-1] if item.SubElementNames else ''; QtCore.QTimer.singleShot(0,lambda:_PANEL.follow_selection(item.Object,sub))
        except Exception: pass
    def clearSelection(self,d): pass
    def removeSelection(self,d,o,s): pass

class Dbl(QtCore.QObject):
    def eventFilter(self,w,e):
        try:
            if e.type()!=QtCore.QEvent.MouseButtonDblClick:return False
            sel=Gui.Selection.getSelection()
            if sel and 'UhryParametrosJSON' in sel[-1].PropertiesList: QtCore.QTimer.singleShot(0,show)
        except Exception: pass
        return False

def _left():
    try:return QtCore.Qt.LeftDockWidgetArea
    except:return QtCore.Qt.DockWidgetArea.LeftDockWidgetArea

def show():
    global _PANEL,_DOCK,_OBS,_FILTER
    if App.ActiveDocument is None: raise ValueError('Abra ou crie um documento.')
    mw=Gui.getMainWindow(); doc=App.ActiveDocument
    if _PANEL is None or _PANEL.doc is not doc:
        if _DOCK:
            try:mw.removeDockWidget(_DOCK);_DOCK.deleteLater()
            except:pass
        _DOCK=QtWidgets.QDockWidget('Direct — Parâmetros',mw); _DOCK.setObjectName('DirectParametersDock'); _PANEL=Panel(doc); _DOCK.setWidget(_PANEL); mw.addDockWidget(_left(),_DOCK)
        for d in mw.findChildren(QtWidgets.QDockWidget):
            txt=((d.windowTitle() or '')+' '+(d.objectName() or '')).casefold()
            if d is not _DOCK and any(x in txt for x in ('tarefas','tasks','combo view','vista combinada')):
                try:mw.tabifyDockWidget(d,_DOCK)
                except:pass
                break
        if _OBS:
            try:Gui.Selection.removeObserver(_OBS)
            except:pass
        _OBS=Obs();Gui.Selection.addObserver(_OBS)
    _PANEL.reload_all();_DOCK.show();_DOCK.raise_();return _PANEL

def hide():
    if _DOCK:_DOCK.hide()
def toggle():
    if _DOCK and _DOCK.isVisible():hide()
    else:show()

def icon_path(): return os.path.join(os.path.dirname(os.path.dirname(__file__)),'Resources','icons','Parameters.svg')
class Command:
    def GetResources(self): return {'MenuText':'Parâmetros','ToolTip':'Parâmetros e vínculos paramétricos Direct','Pixmap':icon_path()}
    def IsActive(self): return App.ActiveDocument is not None
    def Activated(self): toggle()

def _is_direct_action(action):
    try:name=(action.objectName() or '')
    except Exception:name=''
    try:text=(action.text() or '')
    except Exception:text=''
    blob=(name+' '+text).casefold()
    return name.startswith('UhryDirect_') or 'uhrydirect_' in blob or any(k in blob for k in ('linha guia','matriz leve','desenhar na face','converter para body','mover por pontos','peça pelas guias'))

def _find_direct_toolbar(mw):
    best=None;best_score=0
    for tb in mw.findChildren(QtWidgets.QToolBar):
        try:
            if tb.objectName()=='DirectParametersToolbar': continue
            acts=tb.actions()
        except Exception: continue
        score=sum(1 for a in acts if _is_direct_action(a)); title=((tb.windowTitle() or '')+' '+(tb.objectName() or '')).casefold()
        if 'direct' in title: score+=2
        if score>best_score: best=tb;best_score=score
    return best if best_score>0 else None

def _remove_old_separate_toolbar(mw):
    for tb in mw.findChildren(QtWidgets.QToolBar):
        try:
            if tb.objectName()=='DirectParametersToolbar': mw.removeToolBar(tb);tb.deleteLater()
        except Exception: pass

def _ensure_toolbar():
    global _ACTION
    mw=Gui.getMainWindow();_remove_old_separate_toolbar(mw);tb=_find_direct_toolbar(mw)
    if tb is None:return
    for a in tb.actions():
        try:
            if a.objectName()=='UhryDirect_Parameters_Action': _ACTION=a;return
        except Exception:pass
    QAction=getattr(QtGui,'QAction',None) or getattr(QtWidgets,'QAction',None)
    if QAction is None:return
    act=QAction(QtGui.QIcon(icon_path()),'Parâmetros',tb);act.setObjectName('UhryDirect_Parameters_Action');act.setToolTip('Parâmetros e vínculos paramétricos Direct');act.triggered.connect(lambda:Gui.runCommand('UhryDirect_Parameters',0))
    actions=tb.actions();tb.insertAction(actions[0],act) if actions else tb.addAction(act);_ACTION=act

def install():
    global _FILTER,_TIMER
    try:Gui.addCommand('UhryDirect_Parameters',Command())
    except Exception:pass
    app=QtWidgets.QApplication.instance();mw=Gui.getMainWindow()
    if _FILTER:
        try:app.removeEventFilter(_FILTER)
        except Exception:pass
    _FILTER=Dbl(mw);app.installEventFilter(_FILTER)
    _TIMER=QtCore.QTimer(mw);_TIMER.timeout.connect(_ensure_toolbar);_TIMER.start(700);_ensure_toolbar()
