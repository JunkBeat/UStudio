# type: ignore
from __future__ import annotations

from ._common import unitypy_define
from ._part02 import NamedObject
from ._part04 import GlobalGameManager


@unitypy_define
class SpeedTreeWindConfig9:
    m_bDoBranch1: int
    m_bDoBranch2: int
    m_bDoRipple: int
    m_bDoShared: int
    m_bDoShimmer: int
    m_bLodFade: int
    m_fBranch1StretchLimit: float
    m_fBranch2StretchLimit: float
    m_fDirectionResponse: float
    m_fGustDurationMax: float
    m_fGustDurationMin: float
    m_fGustFallScalar: float
    m_fGustFrequency: float
    m_fGustRiseScalar: float
    m_fGustStrengthMax: float
    m_fGustStrengthMin: float
    m_fSharedHeightStart: float
    m_fStrengthResponse: float
    m_fWindIndependence: float
    m_sBranch1: BranchWindLevel
    m_sBranch2: BranchWindLevel
    m_sRipple: RippleGroup
    m_sShared: BranchWindLevel
    m_vTreeExtents: Vector3f
    m_fImportScaling: Optional[float] = None
    pad: Optional[int] = None


@unitypy_define
class SphericalHarmonicsL2:
    sh_10_: float
    sh_11_: float
    sh_12_: float
    sh_13_: float
    sh_14_: float
    sh_15_: float
    sh_16_: float
    sh_17_: float
    sh_18_: float
    sh_19_: float
    sh_20_: float
    sh_21_: float
    sh_22_: float
    sh_23_: float
    sh_24_: float
    sh_25_: float
    sh_26_: float
    sh__0_: float
    sh__1_: float
    sh__2_: float
    sh__3_: float
    sh__4_: float
    sh__5_: float
    sh__6_: float
    sh__7_: float
    sh__8_: float
    sh__9_: float


@unitypy_define
class SplashScreenLogo:
    duration: float
    logo: PPtr[Sprite]


@unitypy_define
class SplatDatabase:
    m_AlphaTextures: List[PPtr[Texture2D]]
    m_AlphamapResolution: int
    m_BaseMapResolution: int
    m_ColorSpace: Optional[int] = None
    m_MaterialRequiresMetallic: Optional[bool] = None
    m_MaterialRequiresSmoothness: Optional[bool] = None
    m_Splats: Optional[List[SplatPrototype]] = None
    m_TerrainLayers: Optional[List[PPtr[TerrainLayer]]] = None


@unitypy_define
class SplatPrototype:
    texture: PPtr[Texture2D]
    tileOffset: Vector2f
    tileSize: Vector2f
    normalMap: Optional[PPtr[Texture2D]] = None
    smoothness: Optional[float] = None
    specularMetallic: Optional[Vector4f] = None


@unitypy_define
class SpriteAtlasAssetData:
    packables: List[PPtr[Object]]


@unitypy_define
class SpriteAtlasData:
    alphaTexture: PPtr[Texture2D]
    downscaleMultiplier: float
    settingsRaw: int
    texture: PPtr[Texture2D]
    textureRect: Rectf
    textureRectOffset: Vector2f
    uvTransform: Vector4f
    atlasRectOffset: Optional[Vector2f] = None
    secondaryTextures: Optional[List[SecondarySpriteTexture]] = None
    spriteInstanceData: Optional[SpriteInstanceData] = None


@unitypy_define
class SpriteAtlasEditorData:
    bindAsDefault: bool
    cachedData: PPtr[CachedSpriteAtlasRuntimeData]
    isAtlasV2: bool
    packables: List[PPtr[Object]]
    packingSettings: PackingSettings
    platformSettings: List[TextureImporterPlatformSettings]
    textureSettings: TextureSettings
    variantMultiplier: float
    secondaryTextureSettings: Optional[List[Tuple[str, SecondaryTextureSettings]]] = None
    storedHash: Optional[Hash128] = None
    totalSpriteSurfaceArea: Optional[int] = None


@unitypy_define
class SpriteBone:
    length: float
    name: str
    parentId: int
    position: Vector3f
    rotation: Quaternionf
    color: Optional[ColorRGBA] = None
    guid: Optional[str] = None


@unitypy_define
class SpriteCustomDataEntry:
    m_Key: str
    m_Value: str


@unitypy_define
class SpriteCustomMetadata:
    m_Entries: List[SpriteCustomDataEntry]


@unitypy_define
class SpriteData:
    sprite: PPtr[Object]


@unitypy_define
class SpriteInstanceData:
    border: Vector4f
    m_Bindpose: List[Matrix4x4f]
    m_BlendShapes: BlendShapeData
    m_IndexBuffer: List[int]
    m_IndexFormat: int
    m_SubMeshes: List[SubMesh]
    m_VertexData: VertexData
    physicsShape: List[List[Vector2f]]
    pivot: Vector2f
    pixelsToUnits: float
    rect: Rectf
    spriteBones: List[SpriteBone]
    spriteName: str


@unitypy_define
class SpriteMetaData:
    m_Alignment: int
    m_Name: str
    m_Pivot: Vector2f
    m_Rect: Rectf
    m_Bones: Optional[List[SpriteBone]] = None
    m_Border: Optional[Vector4f] = None
    m_CustomData: Optional[str] = None
    m_Edges: Optional[List[int2_storage]] = None
    m_Indices: Optional[List[int]] = None
    m_InternalID: Optional[int] = None
    m_Outline: Optional[List[List[Vector2f]]] = None
    m_PhysicsShape: Optional[List[List[Vector2f]]] = None
    m_SpriteID: Optional[str] = None
    m_TessellationDetail: Optional[float] = None
    m_Vertices: Optional[List[Vector2f]] = None
    m_Weights: Optional[List[BoneWeights4]] = None


@unitypy_define
class SpriteRenderData:
    settingsRaw: int
    texture: PPtr[Texture2D]
    textureRect: Rectf
    textureRectOffset: Vector2f
    alphaTexture: Optional[PPtr[Texture2D]] = None
    atlasRectOffset: Optional[Vector2f] = None
    downscaleMultiplier: Optional[float] = None
    indices: Optional[List[int]] = None
    m_Bindpose: Optional[List[Matrix4x4f]] = None
    m_BlendShapes: Optional[BlendShapeData] = None
    m_IndexBuffer: Optional[List[int]] = None
    m_SourceSkin: Optional[List[BoneWeights4]] = None
    m_SubMeshes: Optional[List[SubMesh]] = None
    m_VertexData: Optional[VertexData] = None
    secondaryTextures: Optional[List[SecondarySpriteTexture]] = None
    uvTransform: Optional[Vector4f] = None
    vertices: Optional[List[SpriteVertex]] = None


@unitypy_define
class SpriteSheetMetaData:
    m_Sprites: List[SpriteMetaData]
    m_Bones: Optional[List[SpriteBone]] = None
    m_CustomData: Optional[str] = None
    m_Edges: Optional[List[int2_storage]] = None
    m_Indices: Optional[List[int]] = None
    m_InternalID: Optional[int] = None
    m_NameFileIdTable: Optional[List[Tuple[str, int]]] = None
    m_Outline: Optional[List[List[Vector2f]]] = None
    m_PhysicsShape: Optional[List[List[Vector2f]]] = None
    m_SecondaryTextures: Optional[List[SecondarySpriteTexture]] = None
    m_SpriteCustomMetadata: Optional[SpriteCustomMetadata] = None
    m_SpriteID: Optional[str] = None
    m_Vertices: Optional[List[Vector2f]] = None
    m_Weights: Optional[List[BoneWeights4]] = None


@unitypy_define
class SpriteTilingProperty:
    adaptiveTiling: bool
    adaptiveTilingThreshold: float
    border: Vector4f
    drawMode: int
    newSize: Vector2f
    oldSize: Vector2f
    pivot: Vector2f


@unitypy_define
class SpriteVertex:
    pos: Vector3f
    uv: Optional[Vector2f] = None


@unitypy_define
class State(NamedObject):
    m_IKOnFeet: bool
    m_Motions: List[PPtr[Motion]]
    m_Name: str
    m_ParentStateMachine: PPtr[StateMachine]
    m_Position: Vector3f
    m_Speed: float
    m_Tag: str
    m_CycleOffset: Optional[float] = None
    m_Mirror: Optional[bool] = None


@unitypy_define
class StateConstant:
    m_BlendTreeConstantArray: List[OffsetPtr]
    m_BlendTreeConstantIndexArray: List[int]
    m_IKOnFeet: bool
    m_Loop: bool
    m_Speed: float
    m_TagID: int
    m_TransitionConstantArray: List[OffsetPtr]
    m_CycleOffset: Optional[float] = None
    m_CycleOffsetParamID: Optional[int] = None
    m_FullPathID: Optional[int] = None
    m_ID: Optional[int] = None
    m_LeafInfoArray: Optional[List[LeafInfoConstant]] = None
    m_Mirror: Optional[bool] = None
    m_MirrorParamID: Optional[int] = None
    m_NameID: Optional[int] = None
    m_PathID: Optional[int] = None
    m_SpeedParamID: Optional[int] = None
    m_TimeParamID: Optional[int] = None
    m_WriteDefaultValues: Optional[bool] = None


@unitypy_define
class StateKey:
    m_LayerIndex: int
    m_StateID: int


@unitypy_define
class StateMachine(NamedObject):
    m_AnyStatePosition: Vector3f
    m_ChildStateMachine: List[PPtr[StateMachine]]
    m_ChildStateMachinePosition: List[Vector3f]
    m_DefaultState: PPtr[State]
    m_MotionSetCount: int
    m_Name: str
    m_OrderedTransitions: List[Tuple[PPtr[State], List[PPtr[Transition]]]]
    m_ParentStateMachinePosition: Vector3f
    m_States: List[PPtr[State]]
    m_LocalTransitions: Optional[List[Tuple[PPtr[State], List[PPtr[Transition]]]]] = None


@unitypy_define
class StateMachineBehaviourVectorDescription:
    m_StateMachineBehaviourIndices: List[int]
    m_StateMachineBehaviourRanges: List[Tuple[StateKey, StateRange]]


@unitypy_define
class StateMachineConstant:
    m_AnyStateTransitionConstantArray: List[OffsetPtr]
    m_DefaultState: int
    m_StateConstantArray: List[OffsetPtr]
    m_EvaluateTransitionsOnStart: Optional[bool] = None
    m_MotionSetCount: Optional[int] = None
    m_SelectorStateConstantArray: Optional[List[OffsetPtr]] = None
    m_SynchronizedLayerCount: Optional[int] = None


@unitypy_define
class StateRange:
    m_Count: int
    m_StartIndex: int


@unitypy_define
class StaticBatchInfo:
    firstSubMesh: int
    subMeshCount: int


@unitypy_define
class StreamInfo:
    channelMask: int
    offset: int
    stride: int
    align: Optional[int] = None
    dividerOp: Optional[int] = None
    frequency: Optional[int] = None


@unitypy_define
class StreamedClip:
    curveCount: int
    data: List[int]
    discreteCurveCount: Optional[int] = None


@unitypy_define
class StreamedResource:
    m_Offset: int
    m_Size: int
    m_Source: str


@unitypy_define
class StreamingInfo:
    offset: int
    path: str
    size: int


@unitypy_define
class StructParameter:
    m_ArraySize: int
    m_MatrixMembers: List[MatrixParameter]
    m_NameIndex: int
    m_StructSize: int
    m_VectorMembers: List[VectorParameter]
    m_Index: Optional[int] = None
    m_OffsetInConstantBuffer: Optional[int] = None


@unitypy_define
class SubCollider:
    m_Collider: PPtr[Collider2D]
    m_ColliderPaths: List[List[IntPoint]]


@unitypy_define
class SubEmitterData:
    emitter: PPtr[ParticleSystem]
    properties: int
    type: int
    emitProbability: Optional[float] = None


@unitypy_define
class SubMesh:
    firstByte: int
    firstVertex: int
    indexCount: int
    localAABB: AABB
    vertexCount: int
    baseVertex: Optional[int] = None
    isTriStrip: Optional[int] = None
    topology: Optional[int] = None
    triangleCount: Optional[int] = None


@unitypy_define
class SubModule:
    enabled: bool
    subEmitterBirth: Optional[PPtr[ParticleSystem]] = None
    subEmitterBirth1: Optional[PPtr[ParticleSystem]] = None
    subEmitterCollision: Optional[PPtr[ParticleSystem]] = None
    subEmitterCollision1: Optional[PPtr[ParticleSystem]] = None
    subEmitterDeath: Optional[PPtr[ParticleSystem]] = None
    subEmitterDeath1: Optional[PPtr[ParticleSystem]] = None
    subEmitters: Optional[List[SubEmitterData]] = None


@unitypy_define
class SubPassDescriptor:
    colorOutputs: AttachmentIndexArray
    flags: int
    inputs: AttachmentIndexArray


@unitypy_define
class SubstanceEnumItem:
    text: str
    value: int


@unitypy_define
class SubstanceInput:
    alteredTexturesUID: List[int]
    enumValues: List[SubstanceEnumItem]
    flags: int
    internalIndex: int
    internalType: int
    maximum: float
    minimum: float
    name: str
    step: float
    type: int
    value: SubstanceValue
    componentLabels: Optional[List[str]] = None
    group: Optional[str] = None
    internalIdentifier: Optional[int] = None
    label: Optional[str] = None
    visibleIf: Optional[str] = None


@unitypy_define
class SubstanceValue:
    scalar_0_: float
    scalar_1_: float
    scalar_2_: float
    scalar_3_: float
    texture: PPtr[Texture2D]
    stringvalue: Optional[str] = None


@unitypy_define
class TakeInfo:
    bakeStartTime: float
    bakeStopTime: float
    clip: PPtr[AnimationClip]
    defaultClipName: str
    name: str
    sampleRate: float
    startTime: float
    stopTime: float
    internalID: Optional[int] = None


@unitypy_define
class Tetrahedron:
    indices_0_: int
    indices_1_: int
    indices_2_: int
    indices_3_: int
    matrix: Matrix3x4f
    neighbors_0_: int
    neighbors_1_: int
    neighbors_2_: int
    neighbors_3_: int


@unitypy_define
class TextureImportInstructions:
    colorSpace: int
    compressedFormat: int
    compressionQuality: int
    height: int
    uncompressedFormat: int
    usageMode: int
    width: int
    androidETC2FallbackDownscale: Optional[bool] = None
    androidETC2FallbackFormat: Optional[int] = None
    cubeIntermediateSize: Optional[int] = None
    cubeLayout: Optional[int] = None
    cubeMode: Optional[int] = None
    depth: Optional[int] = None
    desiredFormat: Optional[int] = None
    recommendedFormat: Optional[int] = None
    vtOnly: Optional[bool] = None


@unitypy_define
class TextureImportOutput:
    sourceTextureInformation: SourceTextureInformation
    textureImportInstructions: TextureImportInstructions
    importInspectorWarnings: Optional[str] = None


@unitypy_define
class TextureImporterPlatformSettings:
    m_AllowsAlphaSplitting: bool
    m_AndroidETC2FallbackOverride: int
    m_BuildTarget: str
    m_CompressionQuality: int
    m_CrunchedCompression: bool
    m_MaxTextureSize: int
    m_Overridden: bool
    m_ResizeAlgorithm: int
    m_TextureCompression: int
    m_TextureFormat: int
    m_ForceMaximumCompressionQuality_BC6H_BC7: Optional[bool] = None
    m_IgnorePlatformSupport: Optional[bool] = None


@unitypy_define
class TextureParameter:
    m_Dim: int
    m_NameIndex: int
    m_Binding: Optional[Binding] = None
    m_Index: Optional[int] = None
    m_MultiSampled: Optional[bool] = None
    m_SamplerBinding: Optional[Binding] = None
    m_SamplerIndex: Optional[int] = None


@unitypy_define
class TextureParameters:
    height: int
    mipLevels: int
    textureFormat: int
    width: int


@unitypy_define
class TextureSettings:
    anisoLevel: int
    compressionQuality: int
    crunchedCompression: bool
    filterMode: int
    generateMipMaps: bool
    maxTextureSize: int
    readable: bool
    sRGB: bool
    textureCompression: int


@unitypy_define
class TicksPerSecond:
    m_Denominator: int
    m_Numerator: int


@unitypy_define
class TierGraphicsSettings:
    renderingPath: int
    useCascadedShadowMaps: bool
    enableLPPV: Optional[bool] = None
    hdrMode: Optional[int] = None
    prefer32BitShadowMaps: Optional[bool] = None
    realtimeGICPUUsage: Optional[int] = None
    useHDR: Optional[bool] = None


@unitypy_define
class Tile:
    m_TileColorIndex: int
    m_TileIndex: int
    m_TileMatrixIndex: int
    m_TileSpriteIndex: int
    dummyAlignment: Optional[int] = None
    m_AllTileFlags: Optional[int] = None
    m_ColliderType: Optional[int] = None
    m_ObjectToInstantiate: Optional[PPtr[GameObject]] = None
    m_TileFlags: Optional[int] = None
    m_TileObjectToInstantiateIndex: Optional[int] = None


@unitypy_define
class TileAnimationData:
    m_AnimatedSprites: List[PPtr[Sprite]]
    m_AnimationSpeed: float
    m_AnimationTimeOffset: float
    m_Flags: Optional[int] = None
    m_IsLooping: Optional[bool] = None


@unitypy_define
class TilemapRefCountedData:
    m_Data: Union[ColorRGBA, Matrix4x4f, PPtr[GameObject], PPtr[Object], PPtr[Sprite]]
    m_RefCount: int


@unitypy_define
class TrailModule:
    colorOverLifetime: MinMaxGradient
    colorOverTrail: MinMaxGradient
    dieWithParticles: bool
    enabled: bool
    inheritParticleColor: bool
    lifetime: MinMaxCurve
    minVertexDistance: float
    ratio: float
    sizeAffectsLifetime: bool
    sizeAffectsWidth: bool
    textureMode: int
    widthOverTrail: MinMaxCurve
    worldSpace: bool
    attachRibbonsToTransform: Optional[bool] = None
    generateLightingData: Optional[bool] = None
    mode: Optional[int] = None
    ribbonCount: Optional[int] = None
    shadowBias: Optional[float] = None
    splitSubEmitterRibbons: Optional[bool] = None
    textureScale: Optional[Vector2f] = None


@unitypy_define
class TransformMaskElement:
    m_Path: str
    m_Weight: float


@unitypy_define
class Transition(NamedObject):
    m_Atomic: bool
    m_Conditions: List[Condition]
    m_DstState: PPtr[State]
    m_Mute: bool
    m_Name: str
    m_Solo: bool
    m_SrcState: PPtr[State]
    m_TransitionDuration: float
    m_TransitionOffset: float
    m_CanTransitionToSelf: Optional[bool] = None


@unitypy_define
class TransitionConstant:
    m_ConditionConstantArray: List[OffsetPtr]
    m_DestinationState: int
    m_ID: int
    m_TransitionDuration: float
    m_TransitionOffset: float
    m_UserID: int
    m_Atomic: Optional[bool] = None
    m_CanTransitionToSelf: Optional[bool] = None
    m_ExitTime: Optional[float] = None
    m_FullPathID: Optional[int] = None
    m_HasExitTime: Optional[bool] = None
    m_HasFixedDuration: Optional[bool] = None
    m_InterruptionSource: Optional[int] = None
    m_OrderedInterruption: Optional[bool] = None


@unitypy_define
class TreeInstance:
    color: ColorRGBA
    heightScale: float
    index: int
    lightmapColor: ColorRGBA
    position: Vector3f
    widthScale: float
    rotation: Optional[float] = None


@unitypy_define
class TreePrototype:
    bendFactor: float
    prefab: PPtr[GameObject]
    navMeshLod: Optional[int] = None


@unitypy_define
class TriggerModule:
    enabled: bool
    enter: int
    exit: int
    inside: int
    outside: int
    radiusScale: float
    colliderQueryMode: Optional[int] = None
    collisionShape0: Optional[PPtr[Component]] = None
    collisionShape1: Optional[PPtr[Component]] = None
    collisionShape2: Optional[PPtr[Component]] = None
    collisionShape3: Optional[PPtr[Component]] = None
    collisionShape4: Optional[PPtr[Component]] = None
    collisionShape5: Optional[PPtr[Component]] = None
    primitives: Optional[List[PPtr[Component]]] = None


@unitypy_define
class TypeStats:
    classID: int
    objectCount: int
    resourceCount: int
    size: int


@unitypy_define
class UAVParameter:
    m_NameIndex: int
    m_Binding: Optional[Binding] = None
    m_Index: Optional[int] = None
    m_OriginalBinding: Optional[Binding] = None
    m_OriginalIndex: Optional[int] = None


@unitypy_define
class UVAnimation:
    cycles: float
    x_Tile: int
    y_Tile: int


@unitypy_define
class UVModule:
    animationType: int
    cycles: float
    enabled: bool
    frameOverTime: MinMaxCurve
    rowIndex: int
    tilesX: int
    tilesY: int
    flipU: Optional[float] = None
    flipV: Optional[float] = None
    fps: Optional[float] = None
    mode: Optional[int] = None
    randomRow: Optional[bool] = None
    rowMode: Optional[int] = None
    speedRange: Optional[Vector2f] = None
    sprites: Optional[List[SpriteData]] = None
    startFrame: Optional[MinMaxCurve] = None
    timeMode: Optional[int] = None
    uvChannelMask: Optional[int] = None


@unitypy_define
class UnityAdsSettings(GlobalGameManager):
    m_Enabled: bool
    m_InitializeOnStartup: bool
    m_TestMode: bool
    m_AndroidGameId: Optional[str] = None
    m_EnabledPlatforms: Optional[int] = None
    m_GameId: Optional[str] = None
    m_IosGameId: Optional[str] = None


@unitypy_define
class UnityAnalyticsSettings:
    m_Enabled: bool
    m_TestMode: bool
    m_InitializeOnStartup: Optional[bool] = None
    m_PackageRequiringCoreStatsPresent: Optional[bool] = None
    m_TestConfigUrl: Optional[str] = None
    m_TestEventUrl: Optional[str] = None


@unitypy_define
class UnityPropertySheet:
    m_Colors: Union[List[Tuple[FastPropertyName, ColorRGBA]], List[Tuple[str, ColorRGBA]]]
    m_Floats: Union[List[Tuple[FastPropertyName, float]], List[Tuple[str, float]]]
    m_TexEnvs: Union[List[Tuple[FastPropertyName, UnityTexEnv]], List[Tuple[str, UnityTexEnv]]]
    m_Ints: Optional[List[Tuple[str, int]]] = None


@unitypy_define
class UnityPurchasingSettings:
    m_Enabled: bool
    m_TestMode: bool


@unitypy_define
class UnitySceneHandle:
    value: EntityId


@unitypy_define
class UnityTexEnv:
    m_Offset: Vector2f
    m_Scale: Vector2f
    m_Texture: PPtr[Texture]


@unitypy_define
class UpdateZoneInfo:
    needSwap: bool
    passIndex: int
    rotation: float
    updateZoneCenter: Vector3f
    updateZoneSize: Vector3f


@unitypy_define
class VFXCPUBufferData:
    data: List[int]


@unitypy_define
class VFXCPUBufferDesc:
    capacity: int
    initialData: VFXCPUBufferData
    layout: List[VFXLayoutElementDesc]
    stride: int
    debugName: Optional[str] = None


@unitypy_define
class VFXEditorSystemDesc:
    buffers: List[VFXMapping]
    capacity: int
    flags: int
    layer: int
    tasks: List[VFXEditorTaskDesc]
    type: int
    values: List[VFXMapping]
    name: Optional[str] = None


@unitypy_define
class VFXEditorTaskDesc:
    buffers: List[VFXMapping]
    params: List[VFXMapping]
    processor: PPtr[NamedObject]
    shaderSourceIndex: int
    type: int
    values: List[VFXMapping]
    temporaryBuffers: Optional[List[VFXMappingTemporary]] = None


@unitypy_define
class VFXEntryExposed:
    m_Name: str
    m_Overridden: bool
    m_Value: Union[AnimationCurve, Gradient, Matrix4x4f, PPtr[NamedObject], PPtr[Object], Vector2f, Vector3f, Vector4f, bool, float, int]


@unitypy_define
class VFXEntryExpressionValue:
    m_ExpressionIndex: int
    m_Value: Union[AnimationCurve, Gradient, Matrix4x4f, PPtr[NamedObject], PPtr[Object], Vector2f, Vector3f, Vector4f, bool, float, int]


@unitypy_define
class VFXEventDesc:
    name: str
    playSystems: List[int]
    stopSystems: List[int]
    initSystems: Optional[List[int]] = None


@unitypy_define
class VFXExposedMapping:
    mapping: VFXMapping
    space: int


@unitypy_define
class VFXExpressionContainer:
    m_Expressions: List[Expression]
    m_NeedsLocalToWorld: bool
    m_NeedsWorldToLocal: bool
    m_ConstantBakeCurveCount: Optional[int] = None
    m_ConstantBakeGradientCount: Optional[int] = None
    m_DynamicBakeCurveCount: Optional[int] = None
    m_DynamicBakeGradientCount: Optional[int] = None
    m_MaxCommonExpressionsIndex: Optional[int] = None
    m_NeededMainCameraBuffers: Optional[int] = None
    m_NeedsMainCamera: Optional[bool] = None


@unitypy_define
class VFXField:
    m_Array: Union[List[VFXEntryExposed], List[VFXEntryExpressionValue]]


@unitypy_define
class VFXGPUBufferDesc:
    capacity: int
    layout: List[VFXLayoutElementDesc]
    size: int
    stride: int
    debugName: Optional[str] = None
    mode: Optional[int] = None
    target: Optional[int] = None
    type: Optional[int] = None


@unitypy_define
class VFXInstanceSplitDesc:
    values: List[int]


@unitypy_define
class VFXLayoutElementDesc:
    name: str
    offset: VFXLayoutOffset
    type: int


@unitypy_define
class VFXLayoutOffset:
    bucket: int
    element: int
    structure: int


@unitypy_define
class VFXMapping:
    index: int
    nameId: str


@unitypy_define
class VFXMappingTemporary:
    mapping: VFXMapping
    pastFrameIndex: int
    perCameraBuffer: bool


@unitypy_define
class VFXPropertySheetSerializedBase:
    m_AnimationCurve: VFXField
    m_Bool: VFXField
    m_Float: VFXField
    m_Gradient: VFXField
    m_Int: VFXField
    m_Matrix4x4f: VFXField
    m_NamedObject: VFXField
    m_Uint: VFXField
    m_Vector2f: VFXField
    m_Vector3f: VFXField
    m_Vector4f: VFXField


@unitypy_define
class VFXRendererSettings:
    motionVectorGenerationMode: int
    shadowCastingMode: int
    lightProbeUsage: Optional[int] = None
    rayTracingMode: Optional[int] = None
    receiveShadows: Optional[bool] = None
    reflectionProbeUsage: Optional[int] = None
    transparencyPriority: Optional[int] = None


@unitypy_define
class VFXShaderSourceDesc:
    compute: bool
    name: str
    source: str


@unitypy_define
class VFXSystemDesc:
    buffers: List[VFXMapping]
    capacity: int
    flags: int
    layer: int
    tasks: List[VFXTaskDesc]
    type: int
    values: List[VFXMapping]
    instanceSplitDescs: Optional[List[VFXInstanceSplitDesc]] = None
    name: Optional[str] = None


@unitypy_define
class VFXTaskDesc:
    buffers: List[VFXMapping]
    params: List[VFXMapping]
    processor: Union[PPtr[NamedObject], PPtr[Object]]
    type: int
    values: List[VFXMapping]
    instanceSplitIndex: Optional[int] = None
    temporaryBuffers: Optional[List[VFXMappingTemporary]] = None


@unitypy_define
class VFXTemplate:
    category: str
    description: str
    icon: PPtr[Texture2D]
    name: str
    thumbnail: PPtr[Texture2D]
    order: Optional[int] = None


@unitypy_define
class VFXTemporaryGPUBufferDesc:
    desc: VFXGPUBufferDesc
    frameCount: int


@unitypy_define
class VRSettings:
    cardboard: Optional[Google] = None
    daydream: Optional[Google] = None
    enable360StereoCapture: Optional[bool] = None
    hololens: Optional[HoloLens] = None
    lumin: Optional[Lumin] = None
    none: Optional[DeviceNone] = None
    oculus: Optional[Oculus] = None


@unitypy_define
class ValueArray:
    m_BoolValues: List[bool]
    m_FloatValues: List[float]
    m_IntValues: List[int]
    m_EntityIdValues: Optional[List[EntityId]] = None
    m_PositionValues: Optional[Union[List[float3], List[float4]]] = None
    m_QuaternionValues: Optional[List[float4]] = None
    m_ScaleValues: Optional[Union[List[float3], List[float4]]] = None
    m_VectorValues: Optional[List[float4]] = None


@unitypy_define
class ValueArrayConstant:
    m_ValueArray: List[ValueConstant]


@unitypy_define
class ValueConstant:
    m_ID: int
    m_Index: int
    m_Type: int
    m_TypeID: Optional[int] = None


@unitypy_define
class ValueDelta:
    m_Start: float
    m_Stop: float


@unitypy_define
class VariableBoneCountWeights:
    m_Data: List[int]


@unitypy_define
class VariantInfo:
    graphicsStateInfoSet: Optional[List[GraphicsStateInfo]] = None
    keywordNames: Optional[str] = None
    keywords: Optional[str] = None
    passIndex: Optional[int] = None
    passType: Optional[int] = None
    shader: Optional[PPtr[Shader]] = None
    shaderAssetGUID: Optional[str] = None
    shaderAssetLocalIdentifierInFile: Optional[int] = None
    shaderName: Optional[str] = None
    subShaderIndex: Optional[int] = None


@unitypy_define
class Vector3Curve:
    curve: AnimationCurve
    path: str


@unitypy_define
class VectorParameter:
    m_ArraySize: int
    m_Dim: int
    m_NameIndex: int
    m_Type: int
    m_Index: Optional[int] = None
    m_OffsetInConstantBuffer: Optional[int] = None


@unitypy_define
class VelocityModule:
    enabled: bool
    inWorldSpace: bool
    x: MinMaxCurve
    y: MinMaxCurve
    z: MinMaxCurve
    orbitalOffsetX: Optional[MinMaxCurve] = None
    orbitalOffsetY: Optional[MinMaxCurve] = None
    orbitalOffsetZ: Optional[MinMaxCurve] = None
    orbitalX: Optional[MinMaxCurve] = None
    orbitalY: Optional[MinMaxCurve] = None
    orbitalZ: Optional[MinMaxCurve] = None
    radial: Optional[MinMaxCurve] = None
    speedModifier: Optional[MinMaxCurve] = None


@unitypy_define
class VertexData:
    m_DataSize: bytes
    m_VertexCount: int
    m_Channels: Optional[List[ChannelInfo]] = None
    m_CurrentChannels: Optional[int] = None
    m_Streams: Optional[List[StreamInfo]] = None
    m_Streams_0_: Optional[StreamInfo] = None
    m_Streams_1_: Optional[StreamInfo] = None
    m_Streams_2_: Optional[StreamInfo] = None
    m_Streams_3_: Optional[StreamInfo] = None


@unitypy_define
class VertexLayoutInfo:
    vertexChannelsInfo: List[ChannelInfo]
    vertexStreamCount: int
    vertexStrides: List[int]


@unitypy_define
class VideoClipImporterOutput:
    encodedEndFrame: Optional[int] = None
    encodedHeight: Optional[int] = None
    encodedSettings: Optional[VideoClipImporterTargetSettings] = None
    encodedStartFrame: Optional[int] = None
    encodedWidth: Optional[int] = None
    format: Optional[int] = None
    originalFrameCount: Optional[int] = None
    originalHeight: Optional[int] = None
    originalWidth: Optional[int] = None
    settings: Optional[VideoClipImporterTargetSettings] = None
    sourceAudioChannelCount: Optional[List[int]] = None
    sourceAudioSampleRate: Optional[List[int]] = None
    sourceFileSize: Optional[int] = None
    sourceFrameRate: Optional[float] = None
    sourceHasAlpha: Optional[bool] = None
    sourcePixelAspectRatioDenominator: Optional[int] = None
    sourcePixelAspectRatioNumerator: Optional[int] = None
    streamedResource: Optional[StreamedResource] = None
    transcodeSkipped: Optional[bool] = None


@unitypy_define
class VideoClipImporterTargetSettings:
    aspectRatio: int
    bitrateMode: int
    codec: int
    customHeight: int
    customWidth: int
    enableTranscoding: bool
    resizeFormat: int
    spatialQuality: int


@unitypy_define
class VisualEffectInfo:
    m_Buffers: List[VFXGPUBufferDesc]
    m_CPUBuffers: List[VFXCPUBufferDesc]
    m_CullingFlags: int
    m_Events: List[VFXEventDesc]
    m_ExposedExpressions: Union[List[VFXExposedMapping], List[VFXMapping]]
    m_Expressions: VFXExpressionContainer
    m_PropertySheet: VFXPropertySheetSerializedBase
    m_RendererSettings: VFXRendererSettings
    m_UpdateMode: int
    m_CompilationVersion: Optional[int] = None
    m_InitialEventName: Optional[str] = None
    m_InstancingCapacity: Optional[int] = None
    m_InstancingDisabledReason: Optional[int] = None
    m_InstancingMode: Optional[int] = None
    m_PreWarmDeltaTime: Optional[float] = None
    m_PreWarmStepCount: Optional[int] = None
    m_RuntimeVersion: Optional[int] = None
    m_TemporaryBuffers: Optional[List[VFXTemporaryGPUBufferDesc]] = None


@unitypy_define
class VisualEffectSettings:
    m_CullingFlags: int
    m_InitialEventName: str
    m_PreWarmDeltaTime: float
    m_PreWarmStepCount: int
    m_RendererSettings: VFXRendererSettings
    m_UpdateMode: int
    m_InstancingCapacity: Optional[int] = None
    m_InstancingDisabledReason: Optional[int] = None
    m_InstancingMode: Optional[int] = None


@unitypy_define
class VulkanGraphicsJobsDeviceFilterData:
    filter: AndroidDeviceFilterData
    preferredMode: int


@unitypy_define
class WebGPUDeviceFilterData:
    browserName: str
    browserVersion: str
    browserVersionComparator: int
    deviceType: int
    features: List[int]
    limits: List[WebGPUDeviceFilterLimit]


@unitypy_define
class WebGPUDeviceFilterLimit:
    comparator: int
    limit: int
    value: int


@unitypy_define
class WheelFrictionCurve:
    asymptoteSlip: Optional[float] = None
    asymptoteValue: Optional[float] = None
    extremumSlip: Optional[float] = None
    extremumValue: Optional[float] = None
    m_AsymptoteSlip: Optional[float] = None
    m_AsymptoteValue: Optional[float] = None
    m_ExtremumSlip: Optional[float] = None
    m_ExtremumValue: Optional[float] = None
    m_Stiffness: Optional[float] = None
    stiffnessFactor: Optional[float] = None


@unitypy_define
class bitset:
    bitCount: int
    bitblocks: bytes


@unitypy_define
class int2_storage:
    x: int
    y: int


@unitypy_define
class int3_storage:
    x: int
    y: int
    z: int


@unitypy_define
class xform:
    q: float4
    s: Union[float3, float4]
    t: Union[float3, float4]


