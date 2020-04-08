import vtk

import os, io
import sys, re, hashlib, base64
import json, time, zipfile

from vtk.util import numpy_support
from vtk.vtkFiltersGeometry import vtkCompositeDataGeometryFilter, vtkGeometryFilter
from vtk.vtkCommonCore import vtkTypeUInt32Array


py3 = sys.version_info >= (3,0)

arrayTypesMapping = [
  ' ', # VTK_VOID            0
  ' ', # VTK_BIT             1
  'b', # VTK_CHAR            2
  'B', # VTK_UNSIGNED_CHAR   3
  'h', # VTK_SHORT           4
  'H', # VTK_UNSIGNED_SHORT  5
  'i', # VTK_INT             6
  'I', # VTK_UNSIGNED_INT    7
  'l', # VTK_LONG            8
  'L', # VTK_UNSIGNED_LONG   9
  'f', # VTK_FLOAT          10
  'd', # VTK_DOUBLE         11
  'L', # VTK_ID_TYPE        12
]

javascriptMapping = {
    'b': 'Int8Array',
    'B': 'Uint8Array',
    'h': 'Int16Array',
    'H': 'Int16Array',
    'i': 'Int32Array',
    'I': 'Uint32Array',
    'l': 'Int32Array',
    'L': 'Uint32Array',
    'f': 'Float32Array',
    'd': 'Float64Array'
}

if py3:
    def iteritems(d, **kwargs):
        return iter(d.items(**kwargs))
else:
    def iteritems(d, **kwargs):
        return d.iteritems(**kwargs)

if sys.version_info >= (2,7):
    buffer = memoryview
    base64Encode = lambda x: base64.b64encode(x).decode('utf-8')
else:
    buffer = buffer
    base64Encode = lambda x: x.encode('base64')

def hashDataArray(dataArray):
    hashedBit = base64Encode(hashlib.md5(buffer(dataArray)).digest()).strip()
    md5sum = re.sub('==$', '', hashedBit)
    typeCode = arrayTypesMapping[dataArray.GetDataType()]
    return '%s_%d%s' % (md5sum, dataArray.GetSize(), typeCode)

def getJSArrayType(dataArray):
    return javascriptMapping[arrayTypesMapping[dataArray.GetDataType()]]

# -----------------------------------------------------------------------------
# Convenience class for caching data arrays, storing computed sha sums, keeping
# track of valid actors, etc...
# -----------------------------------------------------------------------------

class SynchronizationContext():
    def __init__(self, debug=False):
        self.dataArrayCache = {}
        self.lastDependenciesMapping = {}
        self.ingoreLastDependencies = False
        self.debugSerializers = debug
        self.debugAll = debug

    def zipCompression(self, name, data):
        with io.BytesIO() as in_memory:
            with zipfile.ZipFile(in_memory, mode="w") as zf:
                zf.writestr(os.path.join('data', name), data, zipfile.ZIP_DEFLATED)
            in_memory.seek(0)
            return in_memory.read()

    def setIgnoreLastDependencies(self, force):
        self.ingoreLastDependencies = force

    def cacheDataArray(self, pMd5, data):
        self.dataArrayCache[pMd5] = data

    def getCachedDataArray(self, pMd5, binary = False, compression = False):
        cacheObj = self.dataArrayCache[pMd5]
        array = cacheObj['array']
        cacheTime = cacheObj['mTime']

        if cacheTime != array.GetMTime():
            if context.debugAll: print(' ***** ERROR: you asked for an old cache key! ***** ')

        if array.GetDataType() == 12:
            # IdType need to be converted to Uint32
            arraySize = array.GetNumberOfTuples() * array.GetNumberOfComponents()
            newArray = vtkTypeUInt32Array()
            newArray.SetNumberOfTuples(arraySize)
            for i in range(arraySize):
                newArray.SetValue(i, -1 if array.GetValue(i) < 0 else array.GetValue(i))
            pBuffer = buffer(newArray)
        else:
            pBuffer = buffer(array)

        if binary:
            # Convert the vtkUnsignedCharArray into a bytes object, required by Autobahn websockets
            return pBuffer.tobytes() if not compression else self.zipCompression(pMd5, pBuffer.tobytes())

        return base64Encode(pBuffer if not compression else self.zipCompression(pMd5, pBuffer.tobytes()))

    def checkForArraysToRelease(self, timeWindow = 20):
        cutOffTime = time.time() - timeWindow
        shasToDelete = []
        for sha in self.dataArrayCache:
            record = self.dataArrayCache[sha]
            array = record['array']
            count = array.GetReferenceCount()

            if count == 1 and record['ts'] < cutOffTime:
                shasToDelete.append(sha)

        for sha in shasToDelete:
            del self.dataArrayCache[sha]

    def getLastDependencyList(self, idstr):
        lastDeps = []
        if idstr in self.lastDependenciesMapping and not self.ingoreLastDependencies:
            lastDeps = self.lastDependenciesMapping[idstr]
        return lastDeps

    def setNewDependencyList(self, idstr, depList):
        self.lastDependenciesMapping[idstr] = depList

    def buildDependencyCallList(self, idstr, newList, addMethod, removeMethod):
        oldList = self.getLastDependencyList(idstr)

        calls = []
        calls += [ [addMethod, [ wrapId(x) ]] for x in newList if x not in oldList ]
        calls += [ [removeMethod, [ wrapId(x) ]] for x in oldList if x not in newList ]

        self.setNewDependencyList(idstr, newList)
        return calls

# -----------------------------------------------------------------------------
# Global variables
# -----------------------------------------------------------------------------

SERIALIZERS = {}
context = None

# -----------------------------------------------------------------------------
# Global API
# -----------------------------------------------------------------------------

def registerInstanceSerializer(name, method):
    global SERIALIZERS
    SERIALIZERS[name] = method

# -----------------------------------------------------------------------------

def serializeInstance(parent, instance, instanceId, context, depth):
    instanceType = instance.GetClassName()
    serializer = SERIALIZERS[instanceType] if instanceType in SERIALIZERS else None

    if serializer:
        return serializer(parent, instance, instanceId, context, depth)

    if context.debugSerializers:
        print('%s!!!No serializer for %s with id %s' % (pad(depth), instanceType, instanceId))

    return None

# -----------------------------------------------------------------------------

def initializeSerializers():
    # Actors/viewProps
    registerInstanceSerializer('vtkOpenGLActor', genericActorSerializer)
    registerInstanceSerializer('vtkPVLODActor', genericActorSerializer)

    # Mappers
    registerInstanceSerializer('vtkOpenGLPolyDataMapper', genericMapperSerializer)
    registerInstanceSerializer('vtkCompositePolyDataMapper2', genericMapperSerializer)
    registerInstanceSerializer('vtkDataSetMapper', genericMapperSerializer)

    # Textures
    registerInstanceSerializer('vtkOpenGLTexture', textureSerializer)

    # LookupTables/TransferFunctions
    registerInstanceSerializer('vtkLookupTable', lookupTableSerializer)
    registerInstanceSerializer('vtkPVDiscretizableColorTransferFunction', colorTransferFunctionSerializer)

    # Property
    registerInstanceSerializer('vtkOpenGLProperty', propertySerializer)

    # Datasets
    registerInstanceSerializer('vtkPolyData', polydataSerializer)
    registerInstanceSerializer('vtkImageData', imagedataSerializer)
    registerInstanceSerializer('vtkMultiBlockDataSet', mergeToPolydataSerializer)
    registerInstanceSerializer('vtkUnstructuredGrid', mergeToPolydataSerializer)

    # RenderWindows
    registerInstanceSerializer('vtkCocoaRenderWindow', renderWindowSerializer)
    registerInstanceSerializer('vtkXOpenGLRenderWindow', renderWindowSerializer)
    registerInstanceSerializer('vtkWin32OpenGLRenderWindow', renderWindowSerializer)
    registerInstanceSerializer('vtkEGLRenderWindow', renderWindowSerializer)
    registerInstanceSerializer('vtkOpenVRRenderWindow', renderWindowSerializer)
    registerInstanceSerializer('vtkGenericOpenGLRenderWindow', renderWindowSerializer)
    registerInstanceSerializer('vtkOSOpenGLRenderWindow', renderWindowSerializer)
    registerInstanceSerializer('vtkOpenGLRenderWindow', renderWindowSerializer)
    registerInstanceSerializer('vtkIOSRenderWindow', renderWindowSerializer)
    registerInstanceSerializer('vtkExternalOpenGLRenderWindow', renderWindowSerializer)

    # Renderers
    registerInstanceSerializer('vtkOpenGLRenderer', rendererSerializer)

    # Cameras
    registerInstanceSerializer('vtkOpenGLCamera', cameraSerializer)

    # Lights
    registerInstanceSerializer('vtkPVLight', lightSerializer)
    registerInstanceSerializer('vtkOpenGLLight', lightSerializer)


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def pad(depth):
    padding = ''
    for _ in range(depth):
        padding += '  '
    return padding

# -----------------------------------------------------------------------------

def wrapId(idStr):
    return 'instance:${%s}' % idStr

# -----------------------------------------------------------------------------

def getReferenceId(ref):
    return ref.__this__[1:17]

# -----------------------------------------------------------------------------

dataArrayShaMapping = {}

def digest(array):
    objId = getReferenceId(array)

    record = None
    if objId in dataArrayShaMapping:
        record = dataArrayShaMapping[objId]

    if record and record['mtime'] == array.GetMTime():
        return record['sha']

    record = {
        'sha': hashDataArray(array),
        'mtime': array.GetMTime()
    }

    dataArrayShaMapping[objId] = record
    return record['sha']

# -----------------------------------------------------------------------------

def getRangeInfo(array, component):
    r = array.GetRange(component)
    compRange = {}
    compRange['min'] = r[0]
    compRange['max'] = r[1]
    compRange['component'] = array.GetComponentName(component)
    return compRange

# -----------------------------------------------------------------------------

def getArrayDescription(array, context):
    if not array:
        return None

    pMd5 = digest(array)
    context.cacheDataArray(pMd5, {
        'array': array,
        'mTime': array.GetMTime(),
        'ts': time.time()
    })

    root = {}
    root['hash'] = pMd5
    root['vtkClass'] = 'vtkDataArray'
    root['name'] = array.GetName()
    root['dataType'] = getJSArrayType(array)
    root['numberOfComponents'] = array.GetNumberOfComponents()
    root['size'] = array.GetNumberOfComponents() * array.GetNumberOfTuples()
    root['ranges'] = []
    if root['numberOfComponents'] > 1:
        for i in range(root['numberOfComponents']):
            root['ranges'].append(getRangeInfo(array, i))
        root['ranges'].append(getRangeInfo(array, -1))
    else:
        root['ranges'].append(getRangeInfo(array, 0))

    return root

# -----------------------------------------------------------------------------

def extractRequiredFields(extractedFields, mapper, dataset, context, requestedFields=['Normals', 'TCoords']):
    # FIXME should evolve and support funky mapper which leverage many arrays
    if mapper.IsA('vtkMapper'):
        scalarVisibility = mapper.GetScalarVisibility()
        colorArrayName = mapper.GetArrayName()
        scalarMode = mapper.GetScalarMode()
        if scalarVisibility and scalarMode in [1, 3]:
            arrayMeta = getArrayDescription(dataset.GetPointData().GetArray(colorArrayName), context)
            if arrayMeta:
                arrayMeta['location'] = 'pointData'
                arrayMeta['registration'] = 'setScalars'
                extractedFields.append(arrayMeta)
        if scalarVisibility and scalarMode in [2, 4]:
            arrayMeta = getArrayDescription(dataset.GetCellData().GetArray(colorArrayName), context)
            if arrayMeta:
                arrayMeta['location'] = 'cellData'
                arrayMeta['registration'] = 'setScalars'
                extractedFields.append(arrayMeta)

    # Normal handling
    if 'Normals' in requestedFields:
        normals = dataset.GetPointData().GetNormals()
        if normals:
            arrayMeta = getArrayDescription(normals, context)
            if arrayMeta:
                arrayMeta['location'] = 'pointData'
                arrayMeta['registration'] = 'setNormals'
                extractedFields.append(arrayMeta)

    # TCoord handling
    if 'TCoords' in requestedFields:
        tcoords = dataset.GetPointData().GetTCoords()
        if tcoords:
            arrayMeta = getArrayDescription(tcoords, context)
            if arrayMeta:
                arrayMeta['location'] = 'pointData'
                arrayMeta['registration'] = 'setTCoords'
                extractedFields.append(arrayMeta)

# -----------------------------------------------------------------------------
# Concrete instance serializers
# -----------------------------------------------------------------------------

def genericActorSerializer(parent, actor, actorId, context, depth):
    # This kind of actor has two "children" of interest, a property and a mapper
    actorVisibility = actor.GetVisibility()
    mapperInstance = None
    propertyInstance = None
    calls = []
    dependencies = []

    if actorVisibility:
        mapper = None
        if not hasattr(actor, 'GetMapper'):
            if context.debugAll: print('This actor does not have a GetMapper method')
        else:
            mapper = actor.GetMapper()

        if mapper:
            mapperId = getReferenceId(mapper)
            mapperInstance = serializeInstance(actor, mapper, mapperId, context, depth + 1)
            if mapperInstance:
                dependencies.append(mapperInstance)
                calls.append(['setMapper', [ wrapId(mapperId) ]])

        prop = None
        if hasattr(actor, 'GetProperty'):
            prop = actor.GetProperty()
        else:
            if context.debugAll: print('This actor does not have a GetProperty method')

        if prop:
            propId = getReferenceId(prop)
            propertyInstance = serializeInstance(actor, prop, propId, context, depth + 1)
            if propertyInstance:
                dependencies.append(propertyInstance)
                calls.append(['setProperty', [ wrapId(propId) ]])

        texture = None
        if hasattr(actor, 'GetTexture'):
            texture = actor.GetTexture()
        else:
            if context.debugAll: print('This actor does not have a GetTexture method')
        
        if texture:
            textureId = getReferenceId(texture)
            textureInstance = serializeInstance(actor, texture, textureId, context, depth + 1)
            if textureInstance:
                dependencies.append(textureInstance)
                calls.append(['addTexture', [ wrapId(textureId) ]])

    if actorVisibility == 0 or (mapperInstance and propertyInstance):
        return {
            'parent': getReferenceId(parent),
            'id': actorId,
            'type': 'vtkActor',
            'properties': {
                # vtkProp
                'visibility': actorVisibility,
                'pickable': actor.GetPickable(),
                'dragable': actor.GetDragable(),
                'useBounds': actor.GetUseBounds(),
                # vtkProp3D
                'origin': actor.GetOrigin(),
                'scale': actor.GetScale(),
                'rotation': [actor.GetMatrix().GetElement(j,i) for i in range(4) for j in range(4)],
                # vtkActor
                'forceOpaque': actor.GetForceOpaque(),
                'forceTranslucent': actor.GetForceTranslucent()
            },
            'calls': calls,
            'dependencies': dependencies
        }

    return None

# -----------------------------------------------------------------------------

def textureSerializer(parent, texture, textureId, context, depth):
    # This kind of mapper requires us to get 2 items: input data and lookup table
    dataObject = None
    dataObjectInstance = None
    calls = []
    dependencies = []

    if hasattr(texture, 'GetInput'):
        dataObject = texture.GetInput()
    else:
        if context.debugAll: print('This texture does not have GetInput method')

    if dataObject:
        dataObjectId = '%s-texture' % textureId
        dataObjectInstance = serializeInstance(texture, dataObject, dataObjectId, context, depth + 1)
        if dataObjectInstance:
            dependencies.append(dataObjectInstance)
            calls.append(['setInputData', [ wrapId(dataObjectId) ]])

    if dataObjectInstance:
        return {
            'parent': getReferenceId(parent),
            'id': textureId,
            'type': 'vtkTexture',
            'properties': {
                'interpolate': texture.GetInterpolate(),
                'repeat': texture.GetRepeat(),
                'edgeClamp': texture.GetEdgeClamp(),
            },
            'calls': calls,
            'dependencies': dependencies
        }

    return None

# -----------------------------------------------------------------------------

def genericMapperSerializer(parent, mapper, mapperId, context, depth):
    # This kind of mapper requires us to get 2 items: input data and lookup table
    dataObject = None
    dataObjectInstance = None
    lookupTableInstance = None
    calls = []
    dependencies = []

    if hasattr(mapper, 'GetInputDataObject'):
        dataObject = mapper.GetInputDataObject(0, 0)
    else:
        if context.debugAll: print('This mapper does not have GetInputDataObject method')

    if dataObject:
        dataObjectId = '%s-dataset' % mapperId
        dataObjectInstance = serializeInstance(mapper, dataObject, dataObjectId, context, depth + 1)
        if dataObjectInstance:
            dependencies.append(dataObjectInstance)
            calls.append(['setInputData', [ wrapId(dataObjectId) ]])

    lookupTable = None

    if hasattr(mapper, 'GetLookupTable'):
        lookupTable = mapper.GetLookupTable()
    else:
        if context.debugAll: print('This mapper does not have GetLookupTable method')

    if lookupTable:
        lookupTableId = getReferenceId(lookupTable)
        lookupTableInstance = serializeInstance(mapper, lookupTable, lookupTableId, context, depth + 1)
        if lookupTableInstance:
            dependencies.append(lookupTableInstance)
            calls.append(['setLookupTable', [ wrapId(lookupTableId) ]])

    if dataObjectInstance and lookupTableInstance:
        return {
            'parent': getReferenceId(parent),
            'id': mapperId,
            'type': 'vtkMapper',
            'properties': {
                'resolveCoincidentTopology': mapper.GetResolveCoincidentTopology(),
                'renderTime': mapper.GetRenderTime(),
                'arrayAccessMode': mapper.GetArrayAccessMode(),
                'scalarRange': mapper.GetScalarRange(),
                'useLookupTableScalarRange': 1 if mapper.GetUseLookupTableScalarRange() else 0,
                'scalarVisibility': mapper.GetScalarVisibility(),
                'colorByArrayName': mapper.GetArrayName(),
                'colorMode': mapper.GetColorMode(),
                'scalarMode': mapper.GetScalarMode(),
                'interpolateScalarsBeforeMapping': 1 if mapper.GetInterpolateScalarsBeforeMapping() else 0
            },
            'calls': calls,
            'dependencies': dependencies
        }

    return None

# -----------------------------------------------------------------------------

def lookupTableSerializer(parent, lookupTable, lookupTableId, context, depth):
    # No children in this case, so no additions to bindings and return empty list
    # But we do need to add instance

    tableArray = lookupTable.GetTable()
    table_ranges = []
    if tableArray.GetNumberOfComponents() > 1:
        for i in range(tableArray.GetNumberOfComponents()):
            table_ranges.append(getRangeInfo(tableArray, i))
        table_ranges.append(getRangeInfo(tableArray, -1))
    else:
        table_ranges.append(getRangeInfo(tableArray, 0))
    
    table = {
        'numberOfComponents': tableArray.GetNumberOfComponents(),
        'size': tableArray.GetSize(),
        'dataType': getJSArrayType(tableArray),
        'ranges': table_ranges,
        'values': numpy_support.vtk_to_numpy(tableArray).ravel().tolist(),
    }

    return {
        'parent': getReferenceId(parent),
        'id': lookupTableId,
        'type': 'vtkLookupTable',
        'properties': {
            'numberOfColors': lookupTable.GetNumberOfColors(),
            'valueRange': lookupTable.GetRange(),
            'hueRange': lookupTable.GetHueRange(),
            # 'alphaRange': lookupTable.GetAlphaRange(),    # Causes weird rendering artifacts on client
            'saturationRange': lookupTable.GetSaturationRange(),
            'nanColor': lookupTable.GetNanColor(),
            'belowRangeColor': lookupTable.GetBelowRangeColor(),
            'aboveRangeColor': lookupTable.GetAboveRangeColor(),
            'useAboveRangeColor': 1 if lookupTable.GetUseAboveRangeColor() else 0,
            'useBelowRangeColor': 1 if lookupTable.GetUseBelowRangeColor() else 0,
            'alpha': lookupTable.GetAlpha(),
            'vectorSize': lookupTable.GetVectorSize(),
            'vectorComponent': lookupTable.GetVectorComponent(),
            'vectorMode': lookupTable.GetVectorMode(),
            'indexedLookup': lookupTable.GetIndexedLookup(),
            # 'table': table,
        },
    }

# -----------------------------------------------------------------------------

def propertySerializer(parent, propObj, propObjId, context, depth):
    representation = propObj.GetRepresentation() if hasattr(propObj, 'GetRepresentation') else 2
    colorToUse = propObj.GetDiffuseColor() if hasattr(propObj, 'GetDiffuseColor') else [1, 1, 1]
    if representation == 1 and hasattr(propObj, 'GetColor'):
        colorToUse = propObj.GetColor()

    return {
        'parent': getReferenceId(parent),
        'id': propObjId,
        'type': 'vtkProperty',
        'properties': {
            'representation': representation,
            'diffuseColor': colorToUse,
            'color': propObj.GetColor(),
            'ambientColor': propObj.GetAmbientColor(),
            'specularColor': propObj.GetSpecularColor(),
            'edgeColor': propObj.GetEdgeColor(),
            'ambient': propObj.GetAmbient(),
            'diffuse': propObj.GetDiffuse(),
            'specular': propObj.GetSpecular(),
            'specularPower': propObj.GetSpecularPower(),
            'opacity': propObj.GetOpacity(),
            'interpolation': propObj.GetInterpolation(),
            'edgeVisibility': 1 if propObj.GetEdgeVisibility() else 0,
            'backfaceCulling': 1 if propObj.GetBackfaceCulling() else 0,
            'frontfaceCulling': 1 if propObj.GetFrontfaceCulling() else 0,
            'pointSize': propObj.GetPointSize(),
            'lineWidth': propObj.GetLineWidth(),
            'lighting': 1 if propObj.GetLighting() else 0,
        }
    }

# -----------------------------------------------------------------------------

def polydataSerializer(parent, dataset, datasetId, context, depth):
    datasetType = dataset.GetClassName()

    if dataset and dataset.GetPoints():
        properties = {}

        # Points
        points = getArrayDescription(dataset.GetPoints().GetData(), context)
        points['vtkClass'] = 'vtkPoints'
        properties['points'] = points

        ## Verts
        if dataset.GetVerts() and dataset.GetVerts().GetData().GetNumberOfTuples() > 0:
            _verts = getArrayDescription(dataset.GetVerts().GetData(), context)
            properties['verts'] = _verts
            properties['verts']['vtkClass'] = 'vtkCellArray'

        ## Lines
        if dataset.GetLines() and dataset.GetLines().GetData().GetNumberOfTuples() > 0:
            _lines = getArrayDescription(dataset.GetLines().GetData(), context)
            properties['lines'] = _lines
            properties['lines']['vtkClass'] = 'vtkCellArray'

        ## Polys
        if dataset.GetPolys() and dataset.GetPolys().GetData().GetNumberOfTuples() > 0:
            _polys = getArrayDescription(dataset.GetPolys().GetData(), context)
            properties['polys'] = _polys
            properties['polys']['vtkClass'] = 'vtkCellArray'

        ## Strips
        if dataset.GetStrips() and dataset.GetStrips().GetData().GetNumberOfTuples() > 0:
            _strips = getArrayDescription(dataset.GetStrips().GetData(), context)
            properties['strips'] = _strips
            properties['strips']['vtkClass'] = 'vtkCellArray'

        ## Fields
        properties['fields'] = []
        extractRequiredFields(properties['fields'], parent, dataset, context)

        return {
            'parent': getReferenceId(parent),
            'id': datasetId,
            'type': datasetType,
            'properties': properties
        }

    if context.debugAll: print('This dataset has no points!')
    return None

# -----------------------------------------------------------------------------
def imagedataSerializer(parent, dataset, datasetId, context, depth):
    datasetType = dataset.GetClassName()
    arrayMeta = getArrayDescription(
        dataset.GetPointData().GetScalars(),
        context
    )
    arrayMeta['location'] = 'pointData'
    arrayMeta['registration'] = 'setScalars'

    if hasattr(dataset, 'GetDirectionMatrix'):
        direction = [dataset.GetDirectionMatrix().GetElement(0,i) for i in range(9)]
    else:
        direction = [1, 0, 0,
                     0, 1, 0,
                     0, 0, 1]

    return {
        'parent': getReferenceId(parent),
        'id': datasetId,
        'type': datasetType,
        'properties' : {
            'spacing': dataset.GetSpacing(),
            'origin': dataset.GetOrigin(),
            'dimensions': dataset.GetDimensions(),
            'direction': direction,
            'fields': [arrayMeta],
        },
    }



# -----------------------------------------------------------------------------

def mergeToPolydataSerializer(parent, dataObject, dataObjectId, context, depth):
    dataset = None

    if dataObject.IsA('vtkCompositeDataSet'):
        if dataObject.GetNumberOfBlocks() == 1:
            dataset = dataObject.GetBlock(0)
        else:
            gf = vtkCompositeDataGeometryFilter()
            gf.SetInputData(dataObject)
            gf.Update()
            dataset = gf.GetOutput()
    elif dataObject.IsA('vtkUnstructuredGrid'):
        gf = vtkGeometryFilter()
        gf.SetInputData(dataObject)
        gf.Update()
        dataset = gf.GetOutput()
    else:
        dataset = dataObject.GetInput()

    return polydataSerializer(parent, dataset, dataObjectId, context, depth)

# -----------------------------------------------------------------------------

def colorTransferFunctionSerializer(parent, instance, objId, context, depth):
    nodes = []

    for i in range(instance.GetSize()):
        # x, r, g, b, midpoint, sharpness
        node = [0, 0, 0, 0, 0, 0]
        instance.GetNodeValue(i, node)
        nodes.append(node)

    return {
        'parent': getReferenceId(parent),
        'id': objId,
        'type': 'vtkColorTransferFunction',
        'properties': {
            'clamping': 1 if instance.GetClamping() else 0,
            'colorSpace': instance.GetColorSpace(),
            'hSVWrap': 1 if instance.GetHSVWrap() else 0,
            # 'nanColor': instance.GetNanColor(),                                    # Breaks client
            # 'belowRangeColor': instance.GetBelowRangeColor(),        # Breaks client
            # 'aboveRangeColor': instance.GetAboveRangeColor(),        # Breaks client
            # 'useAboveRangeColor': True if instance.GetUseAboveRangeColor() else False,
            # 'useBelowRangeColor': True if instance.GetUseBelowRangeColor() else False,
            'allowDuplicateScalars': 1 if instance.GetAllowDuplicateScalars() else 0,
            'alpha': instance.GetAlpha(),
            'vectorComponent': instance.GetVectorComponent(),
            'vectorSize': instance.GetVectorSize(),
            'vectorMode': instance.GetVectorMode(),
            'indexedLookup': instance.GetIndexedLookup(),
            'nodes': nodes
        }
    }

# -----------------------------------------------------------------------------

def rendererSerializer(parent, instance, objId, context, depth):
    dependencies = []
    viewPropIds = []
    lightsIds = []
    calls = []

    # Camera
    camera = instance.GetActiveCamera()
    cameraId = getReferenceId(camera)
    cameraInstance = serializeInstance(instance, camera, cameraId, context, depth + 1)
    if cameraInstance:
        dependencies.append(cameraInstance)
        calls.append(['setActiveCamera', [ wrapId(cameraId) ]])

    # View prop as representation containers
    viewPropCollection = instance.GetViewProps()
    for rpIdx in range(viewPropCollection.GetNumberOfItems()):
        viewProp = viewPropCollection.GetItemAsObject(rpIdx)
        viewPropId = getReferenceId(viewProp)

        viewPropInstance = serializeInstance(instance, viewProp, viewPropId, context, depth + 1)
        if viewPropInstance:
            dependencies.append(viewPropInstance)
            viewPropIds.append(viewPropId)

    calls += context.buildDependencyCallList('%s-props' % objId, viewPropIds, 'addViewProp', 'removeViewProp')

    # Lights
    lightCollection = instance.GetLights()
    for lightIdx in range(lightCollection.GetNumberOfItems()):
        light = lightCollection.GetItemAsObject(lightIdx)
        lightId = getReferenceId(light)

        lightInstance = serializeInstance(instance, light, lightId, context, depth + 1)
        if lightInstance:
            dependencies.append(lightInstance)
            lightsIds.append(lightId)

    calls += context.buildDependencyCallList('%s-lights' % objId, lightsIds, 'addLight', 'removeLight')

    if len(dependencies) > 1:
        return {
            'parent': getReferenceId(parent),
            'id': objId,
            'type': instance.GetClassName(),
            'properties': {
                'background': instance.GetBackground(),
                'background2': instance.GetBackground2(),
                'viewport': instance.GetViewport(),
                ### These commented properties do not yet have real setters in vtk.js
                # 'gradientBackground': instance.GetGradientBackground(),
                # 'aspect': instance.GetAspect(),
                # 'pixelAspect': instance.GetPixelAspect(),
                # 'ambient': instance.GetAmbient(),
                'twoSidedLighting': instance.GetTwoSidedLighting(),
                'lightFollowCamera': instance.GetLightFollowCamera(),
                'layer': instance.GetLayer(),
                'preserveColorBuffer': instance.GetPreserveColorBuffer(),
                'preserveDepthBuffer': instance.GetPreserveDepthBuffer(),
                'nearClippingPlaneTolerance': instance.GetNearClippingPlaneTolerance(),
                'clippingRangeExpansion': instance.GetClippingRangeExpansion(),
                'useShadows': instance.GetUseShadows(),
                'useDepthPeeling': instance.GetUseDepthPeeling(),
                'occlusionRatio': instance.GetOcclusionRatio(),
                'maximumNumberOfPeels': instance.GetMaximumNumberOfPeels()
            },
            'dependencies': dependencies,
            'calls': calls
        }

    return None

# -----------------------------------------------------------------------------

def cameraSerializer(parent, instance, objId, context, depth):
    return {
        'parent': getReferenceId(parent),
        'id': objId,
        'type': 'vtkCamera',
        'properties': {
            'focalPoint': instance.GetFocalPoint(),
            'position': instance.GetPosition(),
            'viewUp': instance.GetViewUp(),
            'clippingRange': instance.GetClippingRange(),
        }
    }

# -----------------------------------------------------------------------------

def lightTypeToString(value):
    """
    #define VTK_LIGHT_TYPE_HEADLIGHT        1
    #define VTK_LIGHT_TYPE_CAMERA_LIGHT 2
    #define VTK_LIGHT_TYPE_SCENE_LIGHT    3

    'HeadLight';
    'SceneLight';
    'CameraLight'
    """
    if value == 1:
        return 'HeadLight'
    elif value == 2:
        return 'CameraLight'

    return 'SceneLight'

def lightSerializer(parent, instance, objId, context, depth):
    return {
        'parent': getReferenceId(parent),
        'id': objId,
        'type': 'vtkLight',
        'properties': {
            # 'specularColor': instance.GetSpecularColor(),
            # 'ambientColor': instance.GetAmbientColor(),
            'switch': instance.GetSwitch(),
            'intensity': instance.GetIntensity(),
            'color': instance.GetDiffuseColor(),
            'position': instance.GetPosition(),
            'focalPoint': instance.GetFocalPoint(),
            'positional': instance.GetPositional(),
            'exponent': instance.GetExponent(),
            'coneAngle': instance.GetConeAngle(),
            'attenuationValues': instance.GetAttenuationValues(),
            'lightType': lightTypeToString(instance.GetLightType()),
            'shadowAttenuation': instance.GetShadowAttenuation(),
        }
    }

# -----------------------------------------------------------------------------

def renderWindowSerializer(parent, instance, objId, context, depth):
    dependencies = []
    rendererIds = []

    rendererCollection = instance.GetRenderers()
    for rIdx in range(rendererCollection.GetNumberOfItems()):
        # Grab the next vtkRenderer
        renderer = rendererCollection.GetItemAsObject(rIdx)
        rendererId = getReferenceId(renderer)
        rendererInstance = serializeInstance(instance, renderer, rendererId, context, depth + 1)
        if rendererInstance:
            dependencies.append(rendererInstance)
            rendererIds.append(rendererId)

    calls = context.buildDependencyCallList(objId, rendererIds, 'addRenderer', 'removeRenderer')

    return {
        'parent': '0x0',
        'id': objId,
        'type': instance.GetClassName(),
        'properties': {
            'numberOfLayers': instance.GetNumberOfLayers()
        },
        'dependencies': dependencies,
        'calls': calls,
        'mtime': instance.GetMTime(),
    }