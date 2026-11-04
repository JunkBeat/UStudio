# type: ignore
from __future__ import annotations

from ._common import ABC, unitypy_define
from ._part02 import AssetImporter, NamedObject
from ._part04 import GlobalGameManager


@unitypy_define
class EmissionModule:
    enabled: bool
    m_BurstCount: int
    cnt0: Optional[int] = None
    cnt1: Optional[int] = None
    cnt2: Optional[int] = None
    cnt3: Optional[int] = None
    cntmax0: Optional[int] = None
    cntmax1: Optional[int] = None
    cntmax2: Optional[int] = None
    cntmax3: Optional[int] = None
    m_Bursts: Optional[List[ParticleSystemEmissionBurst]] = None
    m_Type: Optional[int] = None
    rate: Optional[MinMaxCurve] = None
    rateOverDistance: Optional[MinMaxCurve] = None
    rateOverTime: Optional[MinMaxCurve] = None
    time0: Optional[float] = None
    time1: Optional[float] = None
    time2: Optional[float] = None
    time3: Optional[float] = None


@unitypy_define
class EnlightenCAHMap:
    m_Map: List[Tuple[LookupKey, Hash128]]


@unitypy_define
class EnlightenRendererInformation:
    dynamicLightmapSTInSystem: Vector4f
    instanceHash: Hash128
    renderer: PPtr[Object]
    systemId: int


@unitypy_define
class EnlightenSceneMapping:
    m_Renderers: List[EnlightenRendererInformation]
    m_SystemAtlases: List[EnlightenSystemAtlasInformation]
    m_Systems: List[EnlightenSystemInformation]
    m_TerrainChunks: List[EnlightenTerrainChunksInformation]
    m_CAHMap: Optional[EnlightenCAHMap] = None
    m_Probesets: Optional[List[Hash128]] = None


@unitypy_define
class EnlightenSystemAtlasInformation:
    atlasHash: Hash128
    atlasSize: int
    firstSystemId: int


@unitypy_define
class EnlightenSystemInformation:
    atlasIndex: int
    atlasOffsetX: int
    atlasOffsetY: int
    inputSystemHash: Hash128
    radiositySystemHash: Hash128
    rendererIndex: int
    rendererSize: int


@unitypy_define
class EnlightenTerrainChunksInformation:
    firstSystemId: int
    numChunksInX: int
    numChunksInY: int


@unitypy_define
class EntityId:
    pass


@unitypy_define
class Error:
    filePath: str
    message: str
    severity: int
    startChar: int
    startLine: int


@unitypy_define
class ErrorLog:
    m_HasErrors: bool
    m_Messages: List[Message]


@unitypy_define
class ExpandedData:
    m_ClassID: int
    m_ExpandedProperties: List[str]
    m_InspectorExpanded: bool
    m_ScriptClass: str


@unitypy_define
class ExposedReferenceTable:
    m_References: List[Tuple[str, PPtr[Object]]]


@unitypy_define
class Expression:
    data_0_: int
    data_1_: int
    data_2_: int
    data_3_: int
    op: int
    valueIndex: int
    dataSize: Optional[int] = None
    dataType: Optional[int] = None
    jmpCode: Optional[int] = None
    scalarSwitchCase: Optional[int] = None


@unitypy_define
class ExtensionPropertyValue:
    extensionName: str
    pluginName: str
    propertyName: str
    propertyValue: float


@unitypy_define
class ExternalForcesModule:
    enabled: bool
    influenceFilter: Optional[int] = None
    influenceList: Optional[List[PPtr[ParticleSystemForceField]]] = None
    influenceMask: Optional[BitField] = None
    multiplier: Optional[float] = None
    multiplierCurve: Optional[MinMaxCurve] = None


@unitypy_define
class FalloffTable:
    m_Table_0_: float
    m_Table_10_: float
    m_Table_11_: float
    m_Table_12_: float
    m_Table_1_: float
    m_Table_2_: float
    m_Table_3_: float
    m_Table_4_: float
    m_Table_5_: float
    m_Table_6_: float
    m_Table_7_: float
    m_Table_8_: float
    m_Table_9_: float


@unitypy_define
class FastPropertyName:
    name: str


@unitypy_define
class FlareElement:
    m_Color: ColorRGBA
    m_Fade: bool
    m_ImageIndex: int
    m_Position: float
    m_Rotate: bool
    m_Size: float
    m_UseLightColor: bool
    m_Zoom: bool


@unitypy_define
class FloatCurve:
    attribute: str
    classID: int
    curve: AnimationCurve
    path: str
    script: PPtr[MonoScript]
    flags: Optional[int] = None


@unitypy_define
class ForceModule:
    enabled: bool
    inWorldSpace: bool
    randomizePerFrame: bool
    x: MinMaxCurve
    y: MinMaxCurve
    z: MinMaxCurve


@unitypy_define
class GISettings:
    m_AlbedoBoost: float
    m_BounceScale: float
    m_EnableBakedLightmaps: bool
    m_EnableRealtimeLightmaps: bool
    m_EnvironmentLightingMode: int
    m_IndirectOutputScale: float
    m_TemporalCoherenceThreshold: Optional[float] = None


@unitypy_define
class GLTextureSettings:
    m_Aniso: int
    m_FilterMode: int
    m_MipBias: float
    m_WrapMode: Optional[int] = None
    m_WrapU: Optional[int] = None
    m_WrapV: Optional[int] = None
    m_WrapW: Optional[int] = None


@unitypy_define
class GUID:
    data_0_: int
    data_1_: int
    data_2_: int
    data_3_: int


@unitypy_define
class GenericBinding:
    attribute: int
    customType: int
    isPPtrCurve: int
    path: int
    script: PPtr[Object]
    classID: Optional[int] = None
    isIntCurve: Optional[int] = None
    isSerializeReferenceCurve: Optional[int] = None
    metaData: Optional[int] = None
    typeID: Optional[int] = None


@unitypy_define
class GfxBlendState:
    alphaToMask: int
    rt: List[GfxRenderTargetBlendState]
    separateMRTBlend: int


@unitypy_define
class GfxDepthState:
    depthFunc: int
    depthWrite: int


@unitypy_define
class GfxRasterState:
    conservative: int
    cullMode: int
    depthBias: int
    depthClip: int
    slopeScaledDepthBias: float


@unitypy_define
class GfxRenderTargetBlendState:
    blendOp: int
    blendOpAlpha: int
    dstBlend: int
    dstBlendAlpha: int
    srcBlend: int
    srcBlendAlpha: int
    writeMask: int


@unitypy_define
class GfxStencilState:
    padding: int
    readMask: int
    stencilEnable: int
    stencilFailOpBack: int
    stencilFailOpFront: int
    stencilFuncBack: int
    stencilFuncFront: int
    stencilPassOpBack: int
    stencilPassOpFront: int
    stencilZFailOpBack: int
    stencilZFailOpFront: int
    writeMask: int


@unitypy_define
class Google:
    depthFormat: int
    enableTransitionView: Optional[bool] = None
    enableVideoLayer: Optional[bool] = None
    maximumSupportedHeadTracking: Optional[int] = None
    minimumSupportedHeadTracking: Optional[int] = None
    useProtectedVideoMemory: Optional[bool] = None
    useSustainedPerformanceMode: Optional[bool] = None


@unitypy_define
class Gradient:
    atime0: Optional[int] = None
    atime1: Optional[int] = None
    atime2: Optional[int] = None
    atime3: Optional[int] = None
    atime4: Optional[int] = None
    atime5: Optional[int] = None
    atime6: Optional[int] = None
    atime7: Optional[int] = None
    ctime0: Optional[int] = None
    ctime1: Optional[int] = None
    ctime2: Optional[int] = None
    ctime3: Optional[int] = None
    ctime4: Optional[int] = None
    ctime5: Optional[int] = None
    ctime6: Optional[int] = None
    ctime7: Optional[int] = None
    key0: Optional[ColorRGBA] = None
    key1: Optional[ColorRGBA] = None
    key2: Optional[ColorRGBA] = None
    key3: Optional[ColorRGBA] = None
    key4: Optional[ColorRGBA] = None
    key5: Optional[ColorRGBA] = None
    key6: Optional[ColorRGBA] = None
    key7: Optional[ColorRGBA] = None
    m_ColorSpace: Optional[int] = None
    m_Color_0_: Optional[ColorRGBA] = None
    m_Color_1_: Optional[ColorRGBA] = None
    m_Color_2_: Optional[ColorRGBA] = None
    m_Color_3_: Optional[ColorRGBA] = None
    m_Color_4_: Optional[ColorRGBA] = None
    m_Mode: Optional[int] = None
    m_NumAlphaKeys: Optional[int] = None
    m_NumColorKeys: Optional[int] = None


@unitypy_define
class GradientNEW:
    atime0: int
    atime1: int
    atime2: int
    atime3: int
    atime4: int
    atime5: int
    atime6: int
    atime7: int
    ctime0: int
    ctime1: int
    ctime2: int
    ctime3: int
    ctime4: int
    ctime5: int
    ctime6: int
    ctime7: int
    key0: ColorRGBA
    key1: ColorRGBA
    key2: ColorRGBA
    key3: ColorRGBA
    key4: ColorRGBA
    key5: ColorRGBA
    key6: ColorRGBA
    key7: ColorRGBA
    m_NumAlphaKeys: int
    m_NumColorKeys: int


@unitypy_define
class GraphicsStateInfo:
    appBackface: bool
    depthBias: float
    forceCullMode: int
    invertProjectionMatrix: bool
    renderPass: int
    renderState: int
    slopeDepthBias: float
    subPassIndex: int
    topology: int
    userBackface: bool
    vertexLayout: int
    wireframe: bool
    baseShadingRate: Optional[int] = None
    nonfilteringSamplerBindings: Optional[int] = None
    shadingRateCombinerFragment: Optional[int] = None
    shadingRateCombinerPrimitive: Optional[int] = None
    unfilterableTextureBindings: Optional[int] = None


@unitypy_define
class GroupConnection:
    sendEffectIndex: int
    sourceGroupIndex: int
    targetGroupIndex: int


@unitypy_define
class GroupConstant:
    bypassEffects: bool
    mute: bool
    parentConstantIndex: int
    pitchIndex: int
    solo: bool
    volumeIndex: int
    sendIndex: Optional[int] = None


@unitypy_define
class Hand:
    m_HandBoneIndex: List[int]


@unitypy_define
class HandPose:
    m_CloseOpen: float
    m_DoFArray: List[float]
    m_Grab: float
    m_GrabX: xform
    m_InOut: float
    m_Override: float


@unitypy_define
class Handle:
    m_ID: int
    m_ParentHumanIndex: int
    m_X: xform


@unitypy_define
class Hash128:
    bytes_0_: int
    bytes_10_: int
    bytes_11_: int
    bytes_12_: int
    bytes_13_: int
    bytes_14_: int
    bytes_15_: int
    bytes_1_: int
    bytes_2_: int
    bytes_3_: int
    bytes_4_: int
    bytes_5_: int
    bytes_6_: int
    bytes_7_: int
    bytes_8_: int
    bytes_9_: int


@unitypy_define
class HeightMeshBVNode:
    i: int
    max: Vector3f
    min: Vector3f
    n: int


@unitypy_define
class HeightMeshData:
    m_Bounds: AABB
    m_Indices: List[int]
    m_Nodes: List[HeightMeshBVNode]
    m_Vertices: List[Vector3f]


@unitypy_define
class Heightmap:
    m_Heights: List[int]
    m_Levels: int
    m_MinMaxPatchHeights: List[float]
    m_PrecomputedError: List[float]
    m_Scale: Vector3f
    m_DefaultPhysicMaterial: Optional[PPtr[PhysicMaterial]] = None
    m_EnableHolesTextureCompression: Optional[bool] = None
    m_EnableSurfaceMaskTextureCompression: Optional[bool] = None
    m_Height: Optional[int] = None
    m_Holes: Optional[List[int]] = None
    m_HolesLOD: Optional[List[int]] = None
    m_Resolution: Optional[int] = None
    m_SurfaceMask: Optional[List[int]] = None
    m_SurfaceMaskLOD: Optional[List[int]] = None
    m_Thickness: Optional[float] = None
    m_Width: Optional[int] = None


@unitypy_define
class HeightmapData:
    terrainData: PPtr[Object]
    isRotated: Optional[bool] = None
    position: Optional[Vector3f] = None
    surfaceToTerrain: Optional[Matrix4x4f] = None


@unitypy_define
class HierarchicalSceneData:
    m_SceneGUID: GUID


@unitypy_define
class Hint:
    m_Key: str
    m_Value: str


@unitypy_define
class HoloLens:
    depthFormat: int
    depthBufferSharingEnabled: Optional[bool] = None


@unitypy_define
class Human:
    m_ArmStretch: float
    m_ArmTwist: float
    m_FeetSpacing: float
    m_ForeArmTwist: float
    m_HasLeftHand: bool
    m_HasRightHand: bool
    m_HumanBoneIndex: List[int]
    m_HumanBoneMass: List[float]
    m_LeftHand: OffsetPtr
    m_LegStretch: float
    m_LegTwist: float
    m_RightHand: OffsetPtr
    m_RootX: xform
    m_Scale: float
    m_Skeleton: OffsetPtr
    m_SkeletonPose: OffsetPtr
    m_UpperLegTwist: float
    m_ColliderArray: Optional[List[Collider]] = None
    m_ColliderIndex: Optional[List[int]] = None
    m_Handles: Optional[List[Handle]] = None
    m_HasTDoF: Optional[bool] = None


@unitypy_define
class HumanBone:
    m_BoneName: str
    m_HumanName: str
    m_Limit: SkeletonBoneLimit


@unitypy_define
class HumanDescription:
    m_ArmStretch: float
    m_ArmTwist: float
    m_FeetSpacing: float
    m_ForeArmTwist: float
    m_Human: List[HumanBone]
    m_LegStretch: float
    m_LegTwist: float
    m_RootMotionBoneName: str
    m_Skeleton: List[SkeletonBone]
    m_UpperLegTwist: float
    m_GlobalScale: Optional[float] = None
    m_Handles: Optional[List[HumanHandle]] = None
    m_HasExtraRoot: Optional[bool] = None
    m_HasTranslationDoF: Optional[bool] = None
    m_RootMotionBoneRotation: Optional[Quaternionf] = None
    m_SkeletonHasParents: Optional[bool] = None


@unitypy_define
class HumanGoal:
    m_WeightR: float
    m_WeightT: float
    m_X: xform
    m_HintT: Optional[Union[float3, float4]] = None
    m_HintWeightT: Optional[float] = None


@unitypy_define
class HumanHandle:
    m_BoneName: str
    m_LookAt: bool
    m_Name: str
    m_Position: Vector3f
    m_Rotation: Quaternionf
    m_Scale: Vector3f


@unitypy_define
class HumanLayerConstant:
    m_Binding: int
    m_BodyMask: HumanPoseMask
    m_IKPass: bool
    m_LayerBlendingMode: int
    m_SkeletonMask: OffsetPtr
    m_StateMachineIndex: int
    m_StateMachineMotionSetIndex: int
    m_DefaultWeight: Optional[float] = None
    m_SyncedLayerAffectsTiming: Optional[bool] = None


@unitypy_define
class HumanPose:
    m_DoFArray: List[float]
    m_GoalArray: List[HumanGoal]
    m_LeftHandPose: HandPose
    m_LookAtPosition: Union[float3, float4]
    m_LookAtWeight: float4
    m_RightHandPose: HandPose
    m_RootX: xform
    m_TDoFArray: Optional[Union[List[float3], List[float4]]] = None


@unitypy_define
class HumanPoseMask:
    word0: int
    word1: int
    word2: Optional[int] = None


@unitypy_define
class Image:
    image_data: bytes
    m_Format: int
    m_Height: int
    m_RowBytes: int
    m_Width: int


@unitypy_define
class ImportLog_ImportLogEntry:
    file: str
    line: int
    message: str
    mode: int
    object: PPtr[Object]


@unitypy_define
class InheritVelocityModule:
    enabled: bool
    m_Curve: MinMaxCurve
    m_Mode: int


@unitypy_define
class InitialModule:
    enabled: bool
    gravityModifier: Union[MinMaxCurve, float]
    maxNumParticles: int
    startColor: MinMaxGradient
    startLifetime: MinMaxCurve
    startRotation: MinMaxCurve
    startSize: MinMaxCurve
    startSpeed: MinMaxCurve
    customEmitterVelocity: Optional[Vector3f] = None
    gravitySource: Optional[int] = None
    inheritVelocity: Optional[float] = None
    randomizeRotationDirection: Optional[float] = None
    rotation3D: Optional[bool] = None
    size3D: Optional[bool] = None
    startRotationX: Optional[MinMaxCurve] = None
    startRotationY: Optional[MinMaxCurve] = None
    startSizeY: Optional[MinMaxCurve] = None
    startSizeZ: Optional[MinMaxCurve] = None


@unitypy_define
class InputAxis:
    altNegativeButton: str
    altPositiveButton: str
    axis: int
    dead: float
    descriptiveName: str
    descriptiveNegativeName: str
    gravity: float
    invert: bool
    joyNum: int
    m_Name: str
    negativeButton: str
    positiveButton: str
    sensitivity: float
    snap: bool
    type: int


@unitypy_define
class InputImportSettings:
    name: str
    alphaSource: Optional[int] = None
    aniso: Optional[int] = None
    filterMode: Optional[int] = None
    value: Optional[SubstanceValue] = None
    wrapMode: Optional[int] = None


@unitypy_define
class InsightsSettings:
    m_Enabled: bool
    m_EngineDiagnosticsEnabled: bool
    m_EventUrl: str
    m_StackTraceUrl: str


@unitypy_define
class IntPoint:
    X: int
    Y: int


@unitypy_define
class Item:
    changeFlags: Optional[int] = None
    changeset: Optional[int] = None
    digest: Optional[Union[Hash128, MdFour]] = None
    downloadResolution: Optional[int] = None
    guid: Optional[GUID] = None
    markedForRemoval: Optional[bool] = None
    name: Optional[str] = None
    nameConflictResolution: Optional[int] = None
    oldVersion: Optional[int] = None
    origin: Optional[int] = None
    parent: Optional[GUID] = None
    parentFolderID: Optional[int] = None
    type: Optional[int] = None


@unitypy_define
class JointAngleLimit2D:
    m_LowerAngle: float
    m_UpperAngle: float


@unitypy_define
class JointAngleLimits2D:
    m_LowerAngle: float
    m_UpperAngle: float


@unitypy_define
class JointDrive:
    maximumForce: float
    positionDamper: float
    positionSpring: float
    mode: Optional[int] = None
    useAcceleration: Optional[int] = None


@unitypy_define
class JointLimits:
    max: float
    min: float
    bounceMinVelocity: Optional[float] = None
    bounciness: Optional[float] = None
    contactDistance: Optional[float] = None
    maxBounce: Optional[float] = None
    minBounce: Optional[float] = None


@unitypy_define
class JointMotor:
    force: float
    freeSpin: int
    targetVelocity: float


@unitypy_define
class JointMotor2D:
    m_MaximumMotorForce: float
    m_MotorSpeed: float


@unitypy_define
class JointSpring:
    damper: float
    spring: float
    targetPosition: float


@unitypy_define
class JointSuspension2D:
    m_Angle: float
    m_DampingRatio: float
    m_Frequency: float


@unitypy_define
class JointTranslationLimits2D:
    m_LowerTranslation: float
    m_UpperTranslation: float


@unitypy_define
class Keyframe:
    inSlope: Union[Quaternionf, Vector3f, float]
    outSlope: Union[Quaternionf, Vector3f, float]
    time: float
    value: Union[Quaternionf, Vector3f, float]
    inWeight: Optional[Union[Quaternionf, Vector3f, float]] = None
    outWeight: Optional[Union[Quaternionf, Vector3f, float]] = None
    weightedMode: Optional[int] = None


@unitypy_define
class LOD:
    renderers: List[LODRenderer]
    screenRelativeHeight: float
    fadeMode: Optional[int] = None
    fadeTransitionWidth: Optional[float] = None


@unitypy_define
class LODRenderer:
    renderer: PPtr[Renderer]


@unitypy_define
class LayerConstant:
    m_Binding: int
    m_BodyMask: HumanPoseMask
    m_DefaultWeight: float
    m_IKPass: bool
    m_LayerBlendingMode: int
    m_SkeletonMask: OffsetPtr
    m_StateMachineIndex: int
    m_SyncedLayerAffectsTiming: bool
    m_StateMachineMotionSetIndex: Optional[int] = None
    m_StateMachineSynchronizedLayerIndex: Optional[int] = None


@unitypy_define
class LayoutDataOne:
    m_FloatArray: List[float]


@unitypy_define
class LayoutDataThree:
    m_AnotherFloatArray: List[float]


@unitypy_define
class LayoutDataTwo:
    m_FloatValue: float
    m_IntegerValue: int


@unitypy_define
class LeafInfoConstant:
    m_IDArray: List[int]
    m_IndexOffset: int


@unitypy_define
class LibraryRepresentation:
    name: str
    scriptClassName: str
    thumbnail: Image
    thumbnailClassID: int
    flags: Optional[int] = None
    guid: Optional[GUID] = None
    localIdentifier: Optional[int] = None
    object: Optional[Union[PPtr[EditorExtension], PPtr[Object]]] = None
    path: Optional[str] = None


@unitypy_define
class LifetimeByEmitterSpeedModule:
    enabled: bool
    m_Curve: MinMaxCurve
    m_Range: Vector2f


@unitypy_define
class LightBakingOutput:
    probeOcclusionLightIndex: int
    isBaked: Optional[bool] = None
    lightmapBakeMode: Optional[LightmapBakeMode] = None
    lightmappingMask: Optional[int] = None
    occlusionMaskChannel: Optional[int] = None
    shadowMaskChannel: Optional[int] = None


@unitypy_define
class LightProbeData:
    m_NonTetrahedralizedProbeSetIndexMap: List[Tuple[Hash128, int]]
    m_Positions: List[Vector3f]
    m_ProbeSets: List[ProbeSetIndex]
    m_Tetrahedralization: ProbeSetTetrahedralization


@unitypy_define
class LightProbeOcclusion:
    m_Occlusion: List[float]
    m_BakedLightIndex: Optional[List[int]] = None
    m_OcclusionMaskChannel: Optional[List[int]] = None
    m_ProbeOcclusionLightIndex: Optional[List[int]] = None
    m_ShadowMaskChannel: Optional[List[int]] = None


@unitypy_define
class LightmapBakeMode:
    lightmapBakeType: int
    mixedLightingMode: int


@unitypy_define
class LightmapData:
    m_DirLightmap: Optional[PPtr[Texture2D]] = None
    m_IndirectLightmap: Optional[PPtr[Texture2D]] = None
    m_Lightmap: Optional[PPtr[Texture2D]] = None
    m_ShadowMask: Optional[PPtr[Texture2D]] = None
    sh_0_: Optional[float] = None
    sh_10_: Optional[float] = None
    sh_11_: Optional[float] = None
    sh_12_: Optional[float] = None
    sh_13_: Optional[float] = None
    sh_14_: Optional[float] = None
    sh_15_: Optional[float] = None
    sh_16_: Optional[float] = None
    sh_17_: Optional[float] = None
    sh_18_: Optional[float] = None
    sh_19_: Optional[float] = None
    sh_1_: Optional[float] = None
    sh_20_: Optional[float] = None
    sh_21_: Optional[float] = None
    sh_22_: Optional[float] = None
    sh_23_: Optional[float] = None
    sh_24_: Optional[float] = None
    sh_25_: Optional[float] = None
    sh_26_: Optional[float] = None
    sh_2_: Optional[float] = None
    sh_3_: Optional[float] = None
    sh_4_: Optional[float] = None
    sh_5_: Optional[float] = None
    sh_6_: Optional[float] = None
    sh_7_: Optional[float] = None
    sh_8_: Optional[float] = None
    sh_9_: Optional[float] = None


@unitypy_define
class LightmapSnapshot(NamedObject):
    m_BakedReflectionProbeCubemaps: List[PPtr[Texture]]
    m_BakedReflectionProbes: List[SceneObjectIdentifier]
    m_EnlightenData: List[int]
    m_EnlightenSceneMapping: EnlightenSceneMapping
    m_EnlightenSceneMappingRendererIDs: List[SceneObjectIdentifier]
    m_LightProbes: PPtr[LightProbes]
    m_LightmappedRendererData: List[RendererData]
    m_LightmappedRendererDataIDs: List[SceneObjectIdentifier]
    m_Lightmaps: List[LightmapData]
    m_Lights: List[SceneObjectIdentifier]
    m_Name: str
    m_BakedAmbientProbeInGamma: Optional[SphericalHarmonicsL2] = None
    m_BakedAmbientProbeInLinear: Optional[SphericalHarmonicsL2] = None
    m_BakedAmbientProbesInGamma: Optional[List[SphericalHarmonicsL2]] = None
    m_BakedAmbientProbesInLinear: Optional[List[SphericalHarmonicsL2]] = None
    m_BakedSkyboxProbeCubemaps: Optional[List[PPtr[Texture]]] = None
    m_SceneGUID: Optional[GUID] = None


@unitypy_define
class LightsModule:
    color: bool
    enabled: bool
    intensity: bool
    intensityCurve: MinMaxCurve
    light: PPtr[Light]
    maxLights: int
    randomDistribution: bool
    range: bool
    rangeCurve: MinMaxCurve
    ratio: float


@unitypy_define
class Limit:
    m_Max: Union[float3, float4]
    m_Min: Union[float3, float4]


@unitypy_define
class LineParameters:
    alignment: Optional[int] = None
    colorGradient: Optional[Gradient] = None
    endWidth: Optional[float] = None
    generateLightingData: Optional[bool] = None
    m_EndColor: Optional[ColorRGBA] = None
    m_StartColor: Optional[ColorRGBA] = None
    numCapVertices: Optional[int] = None
    numCornerVertices: Optional[int] = None
    shadowBias: Optional[float] = None
    startWidth: Optional[float] = None
    textureMode: Optional[int] = None
    textureScale: Optional[Vector2f] = None
    widthCurve: Optional[AnimationCurve] = None
    widthMultiplier: Optional[float] = None


@unitypy_define
class LodSelectionCurve:
    m_LodBias: float
    m_LodSlope: float


@unitypy_define
class LookupKey:
    extension: str
    hash: Hash128


@unitypy_define
class Lumin:
    depthFormat: int
    enableGLCache: bool
    frameTiming: int
    glCacheMaxBlobSize: int
    glCacheMaxFileSize: int


@unitypy_define
class MaterialImportOutput:
    baked: int
    currentSettings: BuildTargetSettings


@unitypy_define
class MaterialInstanceSettings:
    buildTargetSettings: List[BuildTargetSettings]
    inputs: List[InputImportSettings]
    materialInformation: ProceduralMaterialInformation
    materialProperties: UnityPropertySheet
    name: str
    prototypeName: str
    textureParameters: List[InputImportSettings]
    lightmapFlags: Optional[int] = None
    renderQueue: Optional[int] = None
    shader: Optional[PPtr[Shader]] = None
    shaderKeywords: Optional[str] = None
    shaderName: Optional[str] = None
    textureAssignments: Optional[List[ProceduralTextureAssignment]] = None


@unitypy_define
class MatrixParameter:
    m_ArraySize: int
    m_NameIndex: int
    m_RowCount: int
    m_Type: int
    m_Index: Optional[int] = None
    m_OffsetInConstantBuffer: Optional[int] = None


@unitypy_define
class MdFour:
    md4_hash: bytes


@unitypy_define
class MeshBlendShape:
    firstVertex: int
    hasNormals: bool
    hasTangents: bool
    vertexCount: int
    aabbMaxDelta: Optional[Vector3f] = None
    aabbMinDelta: Optional[Vector3f] = None
    name: Optional[str] = None


@unitypy_define
class MeshBlendShapeChannel:
    frameCount: int
    frameIndex: int
    name: str
    nameHash: int


@unitypy_define
class MeshBlendShapeVertex:
    index: int
    normal: Vector3f
    tangent: Vector3f
    vertex: Vector3f


@unitypy_define
class MeshLodInfo:
    m_LodSelectionCurve: LodSelectionCurve
    m_NumLevels: int
    m_SubMeshes: List[MeshLodSubMesh]


@unitypy_define
class MeshLodRange:
    m_IndexCount: int
    m_IndexStart: int


@unitypy_define
class MeshLodSubMesh:
    m_Levels: List[MeshLodRange]


@unitypy_define
class Message:
    m_Code: int
    m_Location: SourceLocation
    m_Severity: int
    m_Text: Optional[str] = None


@unitypy_define
class MinMaxAABB:
    m_Max: Vector3f
    m_Min: Vector3f


@unitypy_define
class MinMaxCurve:
    maxCurve: AnimationCurve
    minCurve: AnimationCurve
    minMaxState: int
    scalar: float
    minScalar: Optional[float] = None


@unitypy_define
class MinMaxGradient:
    maxColor: ColorRGBA
    maxGradient: Union[Gradient, GradientNEW]
    minColor: ColorRGBA
    minGradient: Union[Gradient, GradientNEW]
    minMaxState: int


@unitypy_define
class MipmapLimitSettings:
    limitBias: int
    limitBiasMode: int


@unitypy_define
class Module:
    dependencies: List[str]
    name: str
    strippable: bool
    controlledByBuiltinPackage: Optional[bool] = None


@unitypy_define
class MonoAssemblyImporter(AssetImporter):
    m_ExecutionOrder: List[Tuple[str, int]]
    m_IconMap: List[Tuple[str, PPtr[Texture2D]]]
    m_Name: str
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UserData: Optional[str] = None


@unitypy_define
class MonoObject(ABC):
    pass


@unitypy_define
class MotionNeighborList:
    m_NeighborArray: List[int]


@unitypy_define
class MultiModeParameter:
    mode: int
    speed: MinMaxCurve
    spread: float
    value: Optional[float] = None


@unitypy_define
class NameToObjectMap:
    m_ObjectToName: List[Tuple[PPtr[Shader], str]]


@unitypy_define
class NativeType:
    a: int
    b: float
    embedded: EmbeddedNativeType


@unitypy_define
class NavMesh(NamedObject):
    m_Heightmaps: List[HeightmapData]
    m_MeshData: List[int]
    m_Name: str


@unitypy_define
class NavMeshAreaData:
    cost: float
    name: str


@unitypy_define
class NavMeshAreas(GlobalGameManager):
    areas: List[NavMeshAreaData]


@unitypy_define
class NavMeshBuildDebugSettings:
    m_Flags: int


@unitypy_define
class NavMeshBuildSettings:
    agentClimb: float
    agentHeight: float
    agentRadius: float
    agentSlope: float
    agentTypeID: int
    cellSize: float
    ledgeDropHeight: float
    manualCellSize: Union[bool, int]
    manualTileSize: Union[bool, int]
    maxJumpAcrossDistance: float
    minRegionArea: float
    tileSize: int
    accuratePlacement: Optional[Union[bool, int]] = None
    buildHeightMesh: Optional[int] = None
    debug: Optional[NavMeshBuildDebugSettings] = None
    keepTiles: Optional[int] = None
    maxJobWorkers: Optional[int] = None
    preserveTilesOutsideBounds: Optional[int] = None


@unitypy_define
class NavMeshLayerData:
    cost: float
    editType: int
    name: str


@unitypy_define
class NavMeshLayers(GlobalGameManager):
    Built_in_Layer_0: NavMeshLayerData
    Built_in_Layer_1: NavMeshLayerData
    Built_in_Layer_2: NavMeshLayerData
    User_Layer_0: NavMeshLayerData
    User_Layer_1: NavMeshLayerData
    User_Layer_10: NavMeshLayerData
    User_Layer_11: NavMeshLayerData
    User_Layer_12: NavMeshLayerData
    User_Layer_13: NavMeshLayerData
    User_Layer_14: NavMeshLayerData
    User_Layer_15: NavMeshLayerData
    User_Layer_16: NavMeshLayerData
    User_Layer_17: NavMeshLayerData
    User_Layer_18: NavMeshLayerData
    User_Layer_19: NavMeshLayerData
    User_Layer_2: NavMeshLayerData
    User_Layer_20: NavMeshLayerData
    User_Layer_21: NavMeshLayerData
    User_Layer_22: NavMeshLayerData
    User_Layer_23: NavMeshLayerData
    User_Layer_24: NavMeshLayerData
    User_Layer_25: NavMeshLayerData
    User_Layer_26: NavMeshLayerData
    User_Layer_27: NavMeshLayerData
    User_Layer_28: NavMeshLayerData
    User_Layer_3: NavMeshLayerData
    User_Layer_4: NavMeshLayerData
    User_Layer_5: NavMeshLayerData
    User_Layer_6: NavMeshLayerData
    User_Layer_7: NavMeshLayerData
    User_Layer_8: NavMeshLayerData
    User_Layer_9: NavMeshLayerData


@unitypy_define
class NavMeshParams:
    cellSize: float
    tileSize: float
    walkableClimb: float
    walkableHeight: float
    walkableRadius: float


@unitypy_define
class NavMeshTileData:
    m_MeshData: List[int]
    m_Hash: Optional[Hash128] = None


@unitypy_define
class NetworkViewID:
    m_ID: int
    m_Type: int


@unitypy_define
class Node:
    m_AxesId: int
    m_ParentId: int


@unitypy_define
class NoiseModule:
    damping: bool
    enabled: bool
    frequency: float
    octaveMultiplier: float
    octaveScale: float
    octaves: int
    quality: int
    remap: MinMaxCurve
    remapEnabled: bool
    remapY: MinMaxCurve
    remapZ: MinMaxCurve
    scrollSpeed: MinMaxCurve
    separateAxes: bool
    strength: MinMaxCurve
    strengthY: MinMaxCurve
    strengthZ: MinMaxCurve
    positionAmount: Optional[MinMaxCurve] = None
    rotationAmount: Optional[MinMaxCurve] = None
    sizeAmount: Optional[MinMaxCurve] = None


@unitypy_define
class NonAlignedStruct:
    m_Bool: bool


@unitypy_define
class ObjectRolePair:
    m_Object: PPtr[Object]
    m_RolesMask: int


@unitypy_define
class OcclusionScene:
    indexPortals: int
    indexRenderers: int
    scene: GUID
    sizePortals: int
    sizeRenderers: int


@unitypy_define
class Oculus:
    dashSupport: bool
    sharedDepthBuffer: bool
    lowOverheadMode: Optional[bool] = None
    protectedContext: Optional[bool] = None
    v2Signing: Optional[bool] = None


@unitypy_define
class OffsetPtr:
    data: Union[Blend1dDataConstant, Blend2dDataConstant, BlendDirectDataConstant, BlendTreeConstant, BlendTreeNodeConstant, Clip, ConditionConstant, Hand, Human, HumanLayerConstant, LayerConstant, SelectorStateConstant, SelectorTransitionConstant, Skeleton, SkeletonMask, SkeletonPose, StateConstant, StateMachineConstant, TransitionConstant, ValueArray, ValueArrayConstant]


@unitypy_define
class Output:
    hasEmptyFontData: Optional[bool] = None
    importedType: Optional[int] = None
    previewData: Optional[List[float]] = None


@unitypy_define
class PPtrCurve:
    attribute: str
    classID: int
    curve: List[PPtrKeyframe]
    path: str
    script: PPtr[MonoScript]
    flags: Optional[int] = None


@unitypy_define
class PPtrKeyframe:
    time: float
    value: PPtr[Object]


@unitypy_define
class PackedBitVector:
    m_Data: List[int]
    m_NumItems: int
    m_BitSize: Optional[int] = None
    m_Range: Optional[float] = None
    m_Start: Optional[float] = None


@unitypy_define
class PackingSettings:
    allowAlphaSplitting: bool
    blockOffset: int
    enableRotation: bool
    enableTightPacking: bool
    padding: int
    enableAlphaDilation: Optional[bool] = None


@unitypy_define
class Parameter:
    m_GUID: GUID
    m_ParameterName: str


@unitypy_define
class ParserBindChannels:
    m_Channels: List[ShaderBindChannel]
    m_SourceMap: int


@unitypy_define
class ParticleSystemEmissionBurst:
    cycleCount: int
    repeatInterval: float
    time: float
    countCurve: Optional[MinMaxCurve] = None
    maxCount: Optional[int] = None
    minCount: Optional[int] = None
    probability: Optional[float] = None


@unitypy_define
class ParticleSystemForceFieldParameters:
    m_DirectionCurveX: MinMaxCurve
    m_DirectionCurveY: MinMaxCurve
    m_DirectionCurveZ: MinMaxCurve
    m_DragCurve: MinMaxCurve
    m_EndRange: float
    m_GravityCurve: MinMaxCurve
    m_GravityFocus: float
    m_Length: float
    m_MultiplyDragByParticleSize: bool
    m_MultiplyDragByParticleVelocity: bool
    m_RotationAttractionCurve: MinMaxCurve
    m_RotationRandomness: Vector2f
    m_RotationSpeedCurve: MinMaxCurve
    m_Shape: int
    m_StartRange: float
    m_VectorField: PPtr[Texture3D]
    m_VectorFieldAttractionCurve: MinMaxCurve
    m_VectorFieldSpeedCurve: MinMaxCurve


@unitypy_define
class PerLODSettings:
    castShadows: bool
    enableBump: bool
    enableHue: bool
    height: float
    receiveShadows: bool
    reflectionProbeUsage: int
    useLightProbes: bool
    windQuality: int
    enableSettingOverride: Optional[bool] = None
    enableSubsurface: Optional[bool] = None


@unitypy_define
class PerformanceReportingSettings:
    m_Enabled: bool


@unitypy_define
class PhysicMaterial(NamedObject):
    bounceCombine: int
    bounciness: float
    dynamicFriction: float
    frictionCombine: int
    m_Name: str
    staticFriction: float
    dynamicFriction2: Optional[float] = None
    frictionDirection2: Optional[Vector3f] = None
    staticFriction2: Optional[float] = None


