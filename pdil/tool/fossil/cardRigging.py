'''
This wraps up interfacing rig components onto the card structures.
'''
from __future__ import print_function, absolute_import

import collections
from functools import partial
#import inspect
import re
import sys
import traceback

from collections import OrderedDict

from pymel.core import textField, optionMenu, warning, checkBox, intField, floatField, duplicate, move, confirmDialog, selected
#from pymel.core import *

from ...add import shortName
from ... import core
from ... import lib

from . import controllerShape
from . import log
from . import rig
from . import settings
#from . import space
from . import util

try:
    basestring
except NameError:
    basestring = str


class ParamInfo(object):
    '''
    Used by `commandInput` determine what options to make for the user.
    
    ..  todo::
        I think that I'm storing the extra nodes as:
            kwargs=NODE_0;
            
        or whatever number, thought it currently defaults to 0.
    '''

    NODE_0 = 0
    NODE_1 = 1
    NODE_2 = 2
    NODE_3 = 3
    NODE_4 = 4

    NODES = [NODE_0, NODE_1, NODE_2, NODE_3, NODE_4]
    
    INT = -1
    FLOAT = -2
    STR = -3
    BOOL = -4
    ENUM = -5
    CURVE = -6 # Not sure if this is a good idea

    numericTypes = (INT, FLOAT, BOOL)

    def __init__(self, name, desc, type, default=None, min=None, max=None, enum=None):
        self.name = name
        self.desc = desc

        self.type = type
            
        if default is not None:
            self.default = default
        elif type == self.INT:
            self.default = 0
        elif type == self.FLOAT:
            self.default = 0.0
        elif type == self.STR:
            self.default = ''
        elif type == self.BOOL:
            self.default = False
        elif type == self.ENUM:
            # Is this fair to default to the first enum?  Should I assert instead
            raise Exception( 'ParamInfo "{}", "{}" is an enum but specifies no default'.format(name, desc) )
            #self.default = enum.values()[0]
        else:
            # &&& I think this is because curves need a default?
            self.default = None
        
        self.min = min
        self.max = max
        self.value = default
        self.enum = enum
        self.kwargName = '' # Will get filled in when registered via `MetaControl`.
        
    def validate( self, value ):
        # Given a value, assign it to self.value if it meets the min/max reqs.
        if self.min is not None and value < self.min:
            warning( '{0} was lower than the min of {1}, ignoring'.format( value, self.min ) )
            return False
        if self.max is not None and value > self.max:
            warning( '{0} was higher than the max of {1}, ignoring'.format( value, self.max ) )
            return False
        self.value = value
        return True
        
    def __repr__(self):
        return 'ParamInfo( {0}={1} )'.format(self.name, self.value)
    
    def update(self, inputStr):
        settings = self.toDict( inputStr )
        settings[self.name] = self.value
        return self.toStr( settings )

    def getUIFieldKwargs(self, card):
        kwargs = {}
        
        if self.type in [self.INT, self.FLOAT]:
            if self.default is not None:
                kwargs['value'] = self.default
            if self.min is not None:
                kwargs['min'] = self.min
            if self.max is not None:
                kwargs['max'] = self.max
                
        elif self.type == self.BOOL:
            if self.default:
                kwargs['value'] = self.default
                
        elif self.type == self.STR:
            if self.default:
                kwargs['text'] = str(self.default)
        
        elif self.type == self.ENUM:
            # Use the specified default, else default to the first item in the list.
            if self.default:
                kwargs['text'] = self.default
            else:
                kwargs['text'] = self.enum.values()[0]
                
        cardSettings = self.toDict(card.rigParams)
        # Figure out if this option (possibly with multiple choices) is non-default.
        if self.kwargName in cardSettings:
            type = self.determineDataType(cardSettings[self.kwargName])
            
            if type in self.numericTypes:
                kwargs['value'] = cardSettings[self.kwargName]
            elif type == self.NODE_0:
                if card.extraNode[0]:
                    kwargs['text'] = card.extraNode[0].name()
            else:
                kwargs['text'] = cardSettings[self.kwargName]
                
        return kwargs
    
    # &&& I think toDict and toStr are for the options specific to rigging component.
    @classmethod
    def toDict(cls, s):
        '''
        Given a string of options, returns it as a dict.  Reverse of `toStr`
        '''
        
        def toProperDataType(_val):
            '''
            Turns the value from a string to the proper data type.
            ..  todo::
                Probably needs to handle the NODE_* stuff
                
                Can't the ParamInfo just be used to determine data type?
            '''
            _val = _val.strip()
            if _val.startswith( "'" ) and _val.endswith( "'" ):
                return _val[1:-1]
            
            #if _val.isdigit():
            if re.match( '-?\d+$', _val ):
                return int(_val)
            
            if re.match( '-?(\d{0,}\.\d+$)|(\d+\.\d{0,}$)', _val ):
                return float(_val)
            
            if _val == 'False':
                return False
            if _val == 'True':
                return True
            
            return _val
        
        info = {}
        for nameVal in s.split(';'):
            if nameVal.count('='):
                name, val = [_s.strip() for _s in nameVal.split('=')]
                if name and val:
                    # MUST str() because **unpacking kwargs doesn't like unicode!
                    info[str(name)] = toProperDataType(val)
            
        return info
    
    @classmethod
    def toStr(cls, d):
        '''
        Given a dict of options, returns it as a string, Reverse of `toDict`
        '''
        def quoteIfNeeded(data):
            if isinstance( data, basestring ) and not data.startswith('NODE_'):
                return "'" + data + "'"
            return data
        
        temp = [ '{0}={1}'.format(name, quoteIfNeeded(val)) for name, val in d.items() ]
        return ';'.join(temp)
    
    @classmethod
    def determineDataType(cls, value):
        if isinstance( value, int ):
            type = cls.INT
        elif isinstance( value, float ):
            type = cls.FLOAT
        elif value.startswith( 'NODE_0'):
            type = cls.NODE_0
        else:
            type = cls.STR
        return type

    def buildUI(self, card):
        
        uiFieldKwargs = self.getUIFieldKwargs(card)
        
        if self.type == self.BOOL:
            field = checkBox(l='', **uiFieldKwargs )  # noqa e741
            checkBox( field, e=True, cc=core.alt.Callback(self.setParam, field) )
            
        elif self.type == self.INT:
            field = intField(**uiFieldKwargs)
            intField( field, e=True, cc=core.alt.Callback(self.setParam, field) )
            
        elif self.type == self.FLOAT:
            field = floatField(**uiFieldKwargs)
            floatField( field, e=True, cc=core.alt.Callback(self.setParam, field) )
        
        elif self.type == self.ENUM:
            field = optionMenu(l='')  # noqa e741
            optionMenu(field, e=True, cc=core.alt.Callback(self.setParam, field))
            
            for i, choice in enumerate(self.enum, 1):
                menuItem(l=choice)  # noqa e741
                if self.enum[choice] == uiFieldKwargs['text']:
                    optionMenu(field, e=True, sl=i)
        
        elif self.type == self.STR:
            # &&& Possibly super gross, if the field is "name", use the first joint...
            if 'text' not in uiFieldKwargs and self.kwargName == 'name':
                uiFieldKwargs['text'] = shortName(card.joints[0])
                #default = card.n
                #getDefaultIkName(card) # &&& MAKE THIS so I can use the same logic when building the card.
            
            field = textField( **uiFieldKwargs )
            textField( field, e=True, cc=core.alt.Callback(self.setParam, field) )
            setattr(field, 'getValue', field.getText)  # Hack to allow ducktyping.

        elif self.type == self.NODE_0:
            
            def setExtraNode(extraNode):
                card.extraNode[0] = extraNode

                temp = ParamInfo.toDict( card.rigParams )
                temp[self.kwargName] = 'NODE_0'
                card.rigParams = ParamInfo.toStr(temp)

                return True
                
            def clearExtraNode(extraNode):
                card.extraNode[0] = None
                temp = ParamInfo.toDict( card.rigParams )
                del temp[self.kwargName]
                card.rigParams = ParamInfo.toStr(temp)

                return True
            
            util.GetNextSelected(
                setExtraNode,
                clearExtraNode,
                l='',  # noqa e741
                tx=shortName(card.extraNode[0]) if card.extraNode[0] else '',
                cw=[(1, 1), (2, 100), (3, 20)])
    
    def setParam(self, field):
        card = [ o for o in selected() if o.__class__.__name__ == 'Card' ][0]  # Change this to use
        #card = ui.common.selectedCards()[0]  # As a callback, guaranteed to exist
        v = field.getValue()

        # Convert enums to proper name
        if self.type == self.ENUM:
            v = self.enum[v]

        if self.validate(v):
            temp = self.toDict( card.rigParams )
            temp[self.kwargName] = v
            card.rigParams = self.toStr(temp)
    

def colorParity(side, controlSpec={}):
    '''
    Give a dict (used for control spec), subsitute certain colors depending
    on the side.  Also does alignment.
    
    ..  todo::
        The parity dict needs to be exposed to artists elsewhere
        Align only flips right side, is this fair?
        Verify all axis should be flipped
    '''
    
    parity = {  ('R',       'L'):       # noqa e241
                ('green',   'red') }    # noqa e241
    
    # Determine if any color substitution needs to happen.
    for sidePairs, colorPairs in parity.items():
        if side in sidePairs:
            index = sidePairs.index( side )
            otherIndex = int(abs( index - 1 ))
            oldColor = colorPairs[index]
            newColor = colorPairs[otherIndex]
            break
    else:
        return controlSpec

    modifiedSpec = {}
    
    for name, spec in controlSpec.items():
        options = {}
        for optionName, value in spec.items():
            if optionName == 'color':
                parts = value.split()
                if parts[0] == oldColor:
                    parts[0] = newColor
                    value = ' '.join(parts)
                
            if optionName == 'align':
                if side == 'R':
                    if value.startswith('n'):
                        value = value[1:]
                    else:
                        value = 'n' + value
            
            options[optionName] = value
            
        modifiedSpec[name] = options
        
    return {'controlSpec': modifiedSpec}

    
OutputControls = collections.namedtuple( 'OutputControls', 'fk ik' )

if 'registeredControls' not in globals():
    registeredControls = {}


class RegisterdMetaControl(type):
    def __init__(cls, name, bases, clsdict):
        global registeredControls
        if len(cls.mro()) > 2:
            # Register the class in the list of available classes
            registeredControls[name] = cls
            
            # Backfill the key (kwargName) onto the param infos
            if cls.ikInput:
                for kwargName, paramInfo in cls.ikInput.items():
                    if isinstance(paramInfo, ParamInfo):
                        cls.ikInput[kwargName].kwargName = kwargName
                    else:
                        for i, _pi in enumerate(paramInfo):
                            cls.ikInput[kwargName][i].kwargName = kwargName
                            
            if cls.fkInput:
                for kwargName, paramInfo in cls.fkInput.items():
                    if isinstance(paramInfo, ParamInfo):
                        cls.fkInput[kwargName].kwargName = kwargName
                    else:
                        for i, _pi in enumerate(paramInfo):
                            cls.fkInput[kwargName][i].kwargName = kwargName
            
        super(RegisterdMetaControl, cls).__init__(name, bases, clsdict)


class classproperty(object):

    def __init__(self, fget):
        self.fget = fget

    def __get__(self, owner_self, owner_cls):
        return self.fget(owner_cls)


class MetaControl(object):
    '''
    Nearly every control is going to have an IK and FK component.  This allows
    packaging them both up so their args can be inspected and UI derived from it.
    
    The args are of two types:
        Controls Args: size, shape, color etc for the actual controls the
            animators will use

        Component Args: Generally specific to the control being made, as well
            as any shared between ik and fk, like a name
            
    ..  todo::
        * Have optional min/max requirements for if a card can build
            
    Method of overriding for custom stuff
    1) If you have a fancy IK system that will have an FK component, override
        _buildIk()
    2) If you have a special system with NO fk component, override _buildSide
        &&& But can you just set cls.fk = None and override _buildIk()?
            
    '''
    __metaclass__ = RegisterdMetaControl

    displayInUI = True

    shared = {}
    
    # Only relevant to Ik.  Some things only need the a single joint.  Fk can handle a single joint fine.
    hasEndJointInput = True
    
    # ik and fk must take the start and end joint, ikArgs/fkArgs will then be
    # added along with the control spec.
    ik_ = ''
    fk_ = 'pdil.tool.fossil.rig.fkChain'
    
    ikInput = {}
    fkInput = {}
    
    # If this particular control needs the controls to look/sort differently than default
    # ex, Arm wraps IkChain but defaults vigGroup to armIk and armFk
    ikControllerOptions = {}
    fkControllerOptions = {}
    
    # This is for args that are invariant, like if this collection requires fk to translate
    ikArgs = {}
    fkArgs = {}
    
    @classproperty
    def ik(cls):
        if not cls.ik_:
            return None
        
        module, func = cls.ik_.rsplit('.', 1)
        return getattr(sys.modules[module], func)
            
    @classproperty
    def fk(cls):
        if not cls.fk_:
            return None
        
        module, func = cls.fk_.rsplit('.', 1)
        return getattr(sys.modules[module], func)
    
    def _readKwargs(cls, card, isMirroredSide, sideAlteration=lambda **kwargs: kwargs, kinematicType='ik'):
        ikControlSpec = cls.controlOverrides(card, kinematicType)

        kwargs = collections.defaultdict(dict)
        kwargs.update( getattr(cls, kinematicType + 'Args' ))
        kwargs['controlSpec'].update(   getattr(cls, kinematicType + 'ControllerOptions' ) )
        kwargs.update( sideAlteration(**ikControlSpec) )
        
        # Load up the defaults from .ikInput
        validNames = set()
        for argName, paramInfo in getattr(cls, kinematicType + 'Input').items():
            if isinstance( paramInfo, list ):
                paramInfo = paramInfo[0]
            if paramInfo.default is not None:
                kwargs[argName] = paramInfo.default
                
            validNames.add(argName)
        print(validNames, 'Valid names')
        userOverrides = card.rigData.get('ikParams', {}) # ParamInfo.toDict( card.rigParams )
        print(userOverrides)
        # Not sure if decoding nodes is best done here or passed through in ParamInfo.toDict
        for key, val in userOverrides.items():
            print('VALID', key, key in validNames)
            if key in validNames:  # Only copy over valid inputs, incase shenanigans happen
                if val == 'NODE_0':
                    kwargs[key] = card.extraNode[0]
                else:
                    kwargs[key] = val

        return kwargs
    
    readKwargs = classmethod( _readKwargs )
    readIkKwargs = classmethod( partial(_readKwargs, kinematicType='ik') )
    
    readFkKwargs = classmethod( partial(_readKwargs, kinematicType='fk') )

    @classmethod
    def validate(cls, card):
        msg = 'Unable to build card {0} because it does not have any connection to the output joints'.format(card)
        assert card.start().real and card.end().real, msg

    @staticmethod
    def sideAlterationFunc(side):
        '''
        Given a side, ether 'L' or 'R', returns a function that makes changes
        to a dict to change colors if appropriate.
        '''
        
        if side == 'left':
            sideAlteration = partial( colorParity, 'L' )
        elif side == 'right':
            sideAlteration = partial( colorParity, 'R' )
        else:
            sideAlteration = lambda **kwargs: kwargs  # noqa e731
            
        return sideAlteration

    @classmethod
    def _buildSide(cls, card, start, end, isMirroredSide, side=None, buildFk=True):
        chain = rig.getChain(start, end)
        log.Rotation.check(chain, True)
        
        ikCtrl = fkCtrl = None
        sideAlteration = cls.sideAlterationFunc(side)
        
        if cls.fk and buildFk:
            fkControlSpec = cls.controlOverrides(card, 'fk')
            fkGroupName = card.getGroupName( **fkControlSpec )
            
            #kwargs = collections.defaultdict(dict)
            kwargs = cls.readFkKwargs(card, isMirroredSide, sideAlteration)
            kwargs.update( cls.fkArgs )
            kwargs['controlSpec'].update( cls.fkControllerOptions )
            kwargs.update( sideAlteration(**fkControlSpec) )
            
            names = card.nameList(excludeSide=True)
            if side:
                names = [n + settings.controlSideSuffix(side) for n in names]
            kwargs['names'] = names
            
            fkCtrl, fkConstraints = cls.fk( start, end, groupName=fkGroupName, **kwargs )
            
            # If ik is coming, disable fk so ik can lay cleanly on top.  Technically it shouldn't matter but sometimes it does.
            if cls.ik:
                for const in fkConstraints:
                    const.set(0)
            
        if cls.ik:
            name, ikCtrl, ikConstraints = cls._buildIk(card, start, end, side, sideAlteration, isMirroredSide)
        
        switchPlug = None
        if cls.ik and cls.fk and buildFk:
            switchPlug = controllerShape.ikFkSwitch( name, ikCtrl, ikConstraints, fkCtrl, fkConstraints )
        
        log.PostRigRotation.check(chain, card, switchPlug)
        
        return OutputControls(fkCtrl, ikCtrl)

    @classmethod
    def _buildIk(cls, card, start, end, side, sideAlteration, isMirroredSide):
        ikControlSpec = cls.controlOverrides(card, 'ik')
        ikGroupName = card.getGroupName( **ikControlSpec )
        
        kwargs = cls.readIkKwargs(card, isMirroredSide, sideAlteration)

        name = rig.trimName(end)
        
        if 'name' in kwargs and kwargs['name']:
            name = kwargs['name']
        else:
            # If no name is passed in, default to the first joint's
            name = card.nameList(excludeSide=1)[0]
        
        if side == 'left':
            name += settings.controlSideSuffix('left')
        elif side == 'right':
            name += settings.controlSideSuffix('right')
            
        kwargs['name'] = name

        if name.count(' '):  # Hack for splineIk to have different controller names
            name = name.split()[-1]
        
        if cls.hasEndJointInput:
            ikCtrl, ikConstraints = cls.ik( start, end, groupName=ikGroupName, **kwargs )
        else:
            ikCtrl, ikConstraints = cls.ik( start, groupName=ikGroupName, **kwargs )

        return name, ikCtrl, ikConstraints

    @classmethod
    def build(cls, card, buildFk=True):
        '''
        Builds the control(s) and links them to the card
        '''
        cls.validate(card)
        
        log.TooStraight.targetCard(card)
        
        side = card.findSuffix()
        
        if not side or card.isAsymmetric():
            
            if side:
                ctrls = cls._buildSide(card, card.start().real, card.end().real, False, side, buildFk=buildFk)
            else:
                ctrls = cls._buildSide(card, card.start().real, card.end().real, False, buildFk=buildFk)

            if ctrls.ik:
                card.outputCenter.ik = ctrls.ik
            if ctrls.fk:
                card.outputCenter.fk = ctrls.fk
        else:
            # Build one side...
            #side = settings.letterToWord[mirrorCode]
            ctrls = cls._buildSide(card, card.start().real, card.end().real, False, side, buildFk=buildFk)
            if ctrls.ik:
                card.getSide(side).ik = ctrls.ik
            if ctrls.fk:
                card.getSide(side).fk = ctrls.fk
            
            # ... then flip the side info and build the other
            #side = settings.otherLetter(side)
            otherSide = settings.otherSideCode(side)
            #side = settings.otherWord(side)
            ctrls = cls._buildSide(card, card.start().realMirror, card.end().realMirror, True, otherSide, buildFk=buildFk)
            if ctrls.ik:
                card.getSide(otherSide).ik = ctrls.ik
            if ctrls.fk:
                card.getSide(otherSide).fk = ctrls.fk
        
    @classmethod
    def postCreate(cls, card):
        pass
        
    @classmethod
    def controlOverrides(cls, card, kinematicType):
        '''
        Given a card, returns a dict of the override flags for making the controllers.
        
        Must call from the proper inherited class, ex Arm or IkChain NOT MetaControl.
        
        :param str kinematicType: The name of an attr on the class, either 'ik' of 'fk'
        '''
        override = collections.defaultdict( dict )
        
        func = getattr( cls, kinematicType)
        if not func:
            return {}

        # Get the defaults defined by the rig component
        for specName, spec in func.__defaultSpec__.items():
            override[specName] = spec.copy()
        
        # Apply any overrides from the MetaControl
        for specName, spec in getattr(cls, kinematicType + 'ControllerOptions' ).items():
            override[specName].update( spec )

        return {'controlSpec': override}
        
    @classmethod
    def processUniqueArgs(cls, card, funcId):
        #return _argParse( card.getRigComponentOptions(funcId) )
        return {}
        
    @classmethod
    def processSharedArgs(cls, card):
        #return _argParse( card.getRigComponentOptions('shared') )
        return {}

    @classmethod
    def saveState(cls, card):
        pass
        
    @classmethod
    def restoreState(cls, card):
        pass
    

class RotateChain(MetaControl):
    ''' Rotate only controls.  Unless this is a single joint, lead joint is always translatable too. '''
    fkArgs = {'translatable': False}
    fkInput = OrderedDict( [
        ('scalable', ParamInfo('Scalable', 'Scalable', ParamInfo.BOOL, default=False))
    ] )


class TranslateChain(MetaControl):
    ''' Translatable and rotatable controls. '''
    fkArgs = {'translatable': True}
    fkInput = OrderedDict( [
        ('scalable', ParamInfo('Scalable', 'Scalable', ParamInfo.BOOL, default=False))
    ] )


class IkChain(MetaControl):
    ''' Basic 3 joint ik chain. '''
    ik_ = 'pdil.tool.fossil.rig.ikChain2'
    ikInput = OrderedDict( [
        ('name', ParamInfo( 'Name', 'Name', ParamInfo.STR, '')),
        ('pvLen', ParamInfo('PV Length', 'How far the pole vector should be from the chain', ParamInfo.FLOAT, default=0) ),
        ('stretchDefault', ParamInfo('Stretch Default', 'Default value for stretch (set when you `zero`)', ParamInfo.FLOAT, default=1, min=0, max=1)),
        ('endOrientType', ParamInfo('Control Orient', 'How to orient the last control', ParamInfo.ENUM, enum=rig.EndOrient.asChoices(), default=rig.EndOrient.TRUE_ZERO)),
        ('makeBendable', ParamInfo('Make Bendy', 'Adds fine detail controls to adjust each joint individually', ParamInfo.BOOL, default=False) ),
    ] )
    
    ikArgs = {}
    fkArgs = {'translatable': True}
    
    @classmethod
    def readIkKwargs(cls, card, isMirroredSide, sideAlteration):
        kwargs = super(IkChain, cls).readIkKwargs(card, isMirroredSide, sideAlteration)
        '''
        try:
            kwargs['twists'] = json.loads( kwargs['twists'] )
        except Exception:
            kwargs['twists'] = {}
        
        print( 'Parsed into ' + str(type(kwargs['twists'])) + ' ' + str(kwargs['twists']) )
        '''
        
        # Determine the twist joints
        twists = {}

        primaryIndex = -1
        dividerCount = 0
        for j in card.joints:
            if j.info.get('twist'):
                dividerCount += 1
            else:
                if dividerCount:
                    twists[primaryIndex] = dividerCount
                  
                primaryIndex += 1
                dividerCount = 0
        
        kwargs['twists'] = twists
                
        return kwargs










def availableControlTypeNames():
    global registeredControls
    return [name for name, cls in sorted(registeredControls.items()) if cls.displayInUI]
    
    

if 'raiseErrors' not in globals():
    raiseErrors = False


def buildRig(cards):
    '''
    Build the rig for the given cards, defaulting to all of them.
    '''
    global raiseErrors  # Testing hack.
    global registeredControls
    errors = []
    
    #if not cards:
    #    cards =
    
    print( 'Building Cards:\n    ', '    \n'.join( str(c) for c in cards ) )
    
    # Ensure that main and root motion exist
    main = lib.getNodes.mainGroup()
    lib.getNodes.rootMotion(main=main)
    
    # Build all the rig components
    for card in cards:
        if card.rigData.get('rigCmd'):
            try:
                registeredControls[ card.rigData.get('rigCmd') ].build(card)
            except Exception:
                print( traceback.format_exc() )
                errors.append( (card, traceback.format_exc()) )
                
    # Afterwards, create any required space switching that comes default with that card
    for card in cards:
        if card.rigData.get('rigCmd'):
            func = registeredControls[ card.rigData.get('rigCmd') ]
            if func:
                func.postCreate(card)
                
    if errors:
    
        for card, err in errors:
            print( core.text.writeInBox( str(card) + '\n' + err ) )
    
        print( core.text.writeInBox( "The following cards had errors:\n" +
                '\n'.join([str(card) for card, err in errors]) ) ) # noqa e127
                
        confirmDialog( m='Errors occured!  See script editor for details.' )
        
        if raiseErrors:
            raise Exception( 'Errors occured on {0}'.format( errors ) )