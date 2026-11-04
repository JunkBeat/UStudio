# type: ignore
from __future__ import annotations

from ._common import ABC, Object, unitypy_define
from ._part00 import Behaviour
from ._part02 import AssetImporter, NamedObject
from ._part03 import TextAsset


@unitypy_define
class NScreenBridge(Object):
    pass


@unitypy_define
class NativeObjectType(Object):
    m_Inner: NativeType


@unitypy_define
class PackedAssets(Object):
    m_Contents: List[BuildReportPackedAssetInfo]
    m_Overhead: int
    m_ShortPath: str
    m_File: Optional[int] = None


@unitypy_define
class PlatformModuleSetup(Object):
    modules: List[Module]


@unitypy_define
class PluginBuildInfo(Object):
    m_EditorPlugins: List[str]
    m_RuntimePlugins: List[str]


@unitypy_define
class Prefab(Object):
    m_RootGameObject: PPtr[GameObject]
    m_ContainsMissingSerializeReferenceTypes: Optional[bool] = None
    m_HideFlagsBehaviour: Optional[int] = None
    m_IsExploded: Optional[bool] = None
    m_IsPrefabAsset: Optional[bool] = None
    m_IsPrefabParent: Optional[bool] = None
    m_Modification: Optional[PrefabModification] = None
    m_ParentPrefab: Optional[PPtr[Prefab]] = None
    m_SourcePrefab: Optional[PPtr[Prefab]] = None


@unitypy_define
class PrefabInstance(Object):
    m_Modification: PrefabModification
    m_RootGameObject: PPtr[GameObject]
    m_SourcePrefab: PPtr[Prefab]


@unitypy_define
class PresetManager(Object):
    m_DefaultList: Optional[List[DefaultPresetList]] = None
    m_DefaultPresets: Optional[List[Tuple[PresetType, List[DefaultPreset]]]] = None


@unitypy_define
class PropertyModificationsTargetTestObject(Object):
    m_Array: List[PropertyModificationsTargetTestNativeObject]
    m_Data: PropertyModificationsTargetTestNativeObject
    m_FloatTestValue: float
    byte_data: Optional[bytes] = None
    m_Bytes: Optional[List[int]] = None
    m_BytesSize: Optional[int] = None
    m_Floats: Optional[List[float]] = None


@unitypy_define
class RenderPassAttachment(Object):
    pass


@unitypy_define
class SceneRoots(Object):
    m_Roots: List[PPtr[Object]]


@unitypy_define
class SceneVisibilityState(Object):
    m_IsolationMode: Optional[bool] = None
    m_MainStageIsolated: Optional[bool] = None
    m_PrefabStageIsolated: Optional[bool] = None
    m_SceneData: Optional[List[Tuple[SceneIdentifier, SceneVisibilityData]]] = None
    m_ScenePickingData: Optional[SceneDataContainer] = None
    m_SceneVisibilityData: Optional[SceneDataContainer] = None
    m_SceneVisibilityDataIsolated: Optional[SceneDataContainer] = None


@unitypy_define
class ScenesUsingAssets(Object):
    m_ListOfScenesUsingEachAsset: List[Tuple[str, List[str]]]
    m_ScenesUsingAssets: List[BuildReportScenesUsingAsset]


@unitypy_define
class SerializableManagedHost(Object):
    m_Script: PPtr[MonoScript]


@unitypy_define
class SerializableManagedRefTestClass(Object):
    m_Script: PPtr[MonoScript]


@unitypy_define
class ShaderContainer(Object):
    pass


@unitypy_define
class ShaderIncludeReflection(Object):
    m_Functions: List[ReflectedFunction]
    m_ReflectionLog: ErrorLog


@unitypy_define
class SiblingDerived(Object):
    pass


@unitypy_define
class SpriteAtlasDatabase(Object):
    pass


@unitypy_define
class TestObjectVectorPairStringBool(Object):
    m_Map: List[Tuple[str, bool]]
    m_String: str


@unitypy_define
class TestObjectWithSerializedAnimationCurve(Object):
    m_Curve: AnimationCurve


@unitypy_define
class TestObjectWithSerializedArray(Object):
    m_ClampTestValue: float
    m_IntegerArray: List[int]


@unitypy_define
class TestObjectWithSerializedMapStringBool(Object):
    m_Map: List[Tuple[str, bool]]
    m_String: str


@unitypy_define
class TestObjectWithSerializedMapStringNonAlignedStruct(Object):
    m_Map: List[Tuple[str, NonAlignedStruct]]
    m_String: str


@unitypy_define
class TestObjectWithSpecialLayoutOne(Object):
    differentLayout: LayoutDataOne
    sameLayout: LayoutDataOne


@unitypy_define
class TestObjectWithSpecialLayoutTwo(Object):
    differentLayout: LayoutDataTwo
    sameLayout: LayoutDataThree


@unitypy_define
class TilemapEditorUserSettings(Object):
    m_FocusMode: int
    m_LastUsedPalette: PPtr[GameObject]


@unitypy_define
class UIAnimationBinder(Object):
    pass


@unitypy_define
class VersionControlSettings(Object):
    m_Mode: str
    m_CollabEditorSettings: Optional[CollabEditorSettings] = None
    m_TrackPackagesOutsideProject: Optional[bool] = None


@unitypy_define
class VideoBuildInfo(Object):
    m_IsVideoModuleDisabled: bool
    m_VideoClipCount: int


@unitypy_define
class AABB:
    m_Center: Vector3f
    m_Extent: Vector3f


@unitypy_define
class AddedComponent:
    addedObject: PPtr[Component]
    insertIndex: int
    targetCorrespondingSourceObject: PPtr[GameObject]


@unitypy_define
class AddedGameObject:
    addedObject: PPtr[Transform]
    insertIndex: int
    targetCorrespondingSourceObject: PPtr[Transform]


@unitypy_define
class AndroidDeviceFilterData:
    androidOsVersionString: str
    brandName: str
    deviceName: str
    driverVersionString: str
    productName: str
    vendorName: str
    vulkanApiVersionString: str


@unitypy_define
class AnimationClipBindingConstant:
    genericBindings: List[GenericBinding]
    pptrCurveMapping: List[PPtr[Object]]


@unitypy_define
class AnimationClipOverride:
    m_OriginalClip: PPtr[AnimationClip]
    m_OverrideClip: PPtr[AnimationClip]


@unitypy_define
class AnimationCurve:
    m_Curve: List[Keyframe]
    m_PostInfinity: int
    m_PreInfinity: int
    m_RotationOrder: Optional[int] = None


@unitypy_define
class AnimationEvent:
    data: str
    floatParameter: float
    functionName: str
    intParameter: int
    messageOptions: int
    objectReferenceParameter: PPtr[Object]
    time: float


@unitypy_define
class AnimatorCondition:
    m_ConditionEvent: str
    m_ConditionMode: int
    m_EventTreshold: float


@unitypy_define
class Annotation:
    m_ClassID: int
    m_Flags: int
    m_GizmoEnabled: bool
    m_IconEnabled: bool
    m_ScriptClass: str


@unitypy_define
class ArticulationDrive:
    damping: float
    forceLimit: float
    lowerLimit: float
    stiffness: float
    target: float
    targetVelocity: float
    upperLimit: float
    driveType: Optional[int] = None


@unitypy_define
class AspectRatios:
    Others: bool
    x16_10: bool
    x16_9: bool
    x4_3: bool
    x5_4: bool


@unitypy_define
class AssemblyJsonAsset(TextAsset):
    m_Name: str
    m_Script: str
    m_PathName: Optional[str] = None


@unitypy_define
class AssemblyJsonImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_Name: str
    m_UserData: str
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None


@unitypy_define
class Asset:
    children: List[GUID]
    labels: AssetLabels
    mainRepresentation: LibraryRepresentation
    parent: GUID
    representations: List[LibraryRepresentation]
    type: int
    assetBundleIndex: Optional[int] = None
    digest: Optional[MdFour] = None
    guidOfPathLocationDependencies: Optional[Union[List[Tuple[GUID, str]], List[Tuple[str, GUID]]]] = None
    hash: Optional[Union[Hash128, MdFour]] = None
    hashOfImportedAssetDependencies: Optional[List[GUID]] = None
    hashOfSourceAssetDependencies: Optional[List[GUID]] = None
    importerClassId: Optional[int] = None
    importerVersionHash: Optional[int] = None
    metaModificationDate_0_: Optional[int] = None
    metaModificationDate_1_: Optional[int] = None
    modificationDate_0_: Optional[int] = None
    modificationDate_1_: Optional[int] = None
    scriptedImporterClassID: Optional[str] = None


@unitypy_define
class AssetBundleFullName:
    m_AssetBundleName: str
    m_AssetBundleVariant: str


@unitypy_define
class AssetBundleInfo:
    AssetBundleDependencies: List[int]
    AssetBundleHash: Hash128


@unitypy_define
class AssetBundleScriptInfo:
    assemblyName: str
    className: str
    hash: int
    nameSpace: str


@unitypy_define
class AssetDatabase(Object):
    m_Assets: List[Tuple[GUID, Asset]]
    m_AssetBundleNames: Optional[List[Tuple[int, AssetBundleFullName]]] = None
    m_AssetTimeStamps: Optional[List[Tuple[str, AssetTimeStamp]]] = None
    m_Metrics: Optional[AssetDatabaseMetrics] = None
    m_UnityShadersVersion: Optional[int] = None
    m_lastValidVersionHashes: Optional[List[Tuple[int, int]]] = None


@unitypy_define
class AssetDatabaseMetrics:
    totalAssetCount: int
    nonProAssetCount: Optional[int] = None
    nonProAssetsCreatedAfterProLicense: Optional[int] = None


@unitypy_define
class AssetImporterHashKey:
    ScriptClass: str
    type: int


@unitypy_define
class AssetImporterLog(NamedObject):
    m_Logs: List[AssetImporter_ImportError]
    m_Name: str


@unitypy_define
class AssetImporter_ImportError:
    error: str
    file: str
    line: int
    mode: int
    object: PPtr[Object]


@unitypy_define
class AssetInfo:
    asset: PPtr[Object]
    preloadIndex: int
    preloadSize: int


@unitypy_define
class AssetLabels:
    m_Labels: List[str]


@unitypy_define
class AssetStats:
    objectCount: int
    resourceCount: int
    size: int
    sourceAssetGUID: GUID
    sourceAssetPath: str


@unitypy_define
class AssetTimeStamp:
    metaModificationDate_0_: int
    metaModificationDate_1_: int
    modificationDate_0_: int
    modificationDate_1_: int


@unitypy_define
class AttachmentIndexArray:
    activeAttachments: int
    attachments: List[int]


@unitypy_define
class AttachmentInfo:
    format: int
    needsResolve: bool
    canMultiview: Optional[bool] = None
    loadAction: Optional[int] = None
    sampleCount: Optional[int] = None
    storeAction: Optional[int] = None


@unitypy_define
class AudioImporterOutput:
    editorOutputContainerFormat: int
    editorOutputSettings: SampleSettings
    outputContainerFormat: int
    outputSettings: SampleSettings
    playerResource: Optional[StreamedResource] = None


@unitypy_define
class AudioMixerConstant:
    effectGUIDs: List[GUID]
    effects: List[EffectConstant]
    exposedParameterIndices: List[int]
    exposedParameterNames: List[int]
    groupGUIDs: List[GUID]
    groupNameBuffer: List[int]
    groups: List[GroupConstant]
    numSideChainBuffers: int
    pluginEffectNameBuffer: List[int]
    snapshotGUIDs: List[GUID]
    snapshotNameBuffer: List[int]
    snapshots: List[SnapshotConstant]
    groupConnections: Optional[List[GroupConnection]] = None


@unitypy_define
class AudioMixerLiveUpdateBool(ABC):
    pass


@unitypy_define
class AudioMixerLiveUpdateFloat(ABC):
    pass


@unitypy_define
class AutoOffMeshLinkData:
    m_Area: int
    m_End: Vector3f
    m_LinkDirection: int
    m_LinkType: int
    m_Radius: float
    m_Start: Vector3f


@unitypy_define
class AvatarBodyMask(NamedObject):
    m_Mask: List[int]
    m_Name: str


@unitypy_define
class AvatarConstant:
    m_Human: OffsetPtr
    m_HumanSkeletonIndexArray: List[int]
    m_RootMotionBoneIndex: int
    m_RootMotionBoneX: xform
    m_AvatarSkeleton: Optional[OffsetPtr] = None
    m_AvatarSkeletonPose: Optional[OffsetPtr] = None
    m_DefaultPose: Optional[OffsetPtr] = None
    m_HumanSkeletonReverseIndexArray: Optional[List[int]] = None
    m_RootMotionSkeleton: Optional[OffsetPtr] = None
    m_RootMotionSkeletonIndexArray: Optional[List[int]] = None
    m_RootMotionSkeletonPose: Optional[OffsetPtr] = None
    m_Skeleton: Optional[OffsetPtr] = None
    m_SkeletonNameIDArray: Optional[List[int]] = None
    m_SkeletonPose: Optional[OffsetPtr] = None


@unitypy_define
class AvatarSkeletonMaskElement:
    path: str
    weight: float


@unitypy_define
class Axes:
    m_Length: float
    m_Limit: Limit
    m_PostQ: float4
    m_PreQ: float4
    m_Sgn: Union[float3, float4]
    m_Type: int


@unitypy_define
class Binding:
    m_Slot: int
    m_EncodedData: Optional[int] = None
    m_Set: Optional[int] = None


@unitypy_define
class BitField:
    m_Bits: int


@unitypy_define
class Blend1dDataConstant:
    m_ChildThresholdArray: List[float]


@unitypy_define
class Blend2dDataConstant:
    m_ChildMagnitudeArray: Optional[List[float]] = None
    m_ChildNeighborListArray: Optional[List[MotionNeighborList]] = None
    m_ChildPairAvgMagInvArray: Optional[List[float]] = None
    m_ChildPairVectorArray: Optional[List[Vector2f]] = None
    m_ChildPositionArray: Optional[List[Vector2f]] = None
    m_ChildThresholdArray: Optional[List[float]] = None


@unitypy_define
class BlendDirectDataConstant:
    m_ChildBlendEventIDArray: List[int]
    m_NormalizedBlendValues: bool


@unitypy_define
class BlendShapeData:
    channels: List[MeshBlendShapeChannel]
    fullWeights: List[float]
    shapes: List[MeshBlendShape]
    vertices: List[BlendShapeVertex]


@unitypy_define
class BlendShapeVertex:
    index: int
    normal: Vector3f
    tangent: Vector3f
    vertex: Vector3f


@unitypy_define
class BlendTreeConstant:
    m_NodeArray: List[OffsetPtr]
    m_BlendEventArrayConstant: Optional[OffsetPtr] = None


@unitypy_define
class BlendTreeNodeConstant:
    m_BlendEventID: int
    m_ChildIndices: List[int]
    m_ClipID: int
    m_Duration: float
    m_Blend1dData: Optional[OffsetPtr] = None
    m_Blend2dData: Optional[OffsetPtr] = None
    m_BlendDirectData: Optional[OffsetPtr] = None
    m_BlendEventYID: Optional[int] = None
    m_BlendType: Optional[int] = None
    m_ChildThresholdArray: Optional[List[float]] = None
    m_ClipIndex: Optional[int] = None
    m_CycleOffset: Optional[float] = None
    m_Mirror: Optional[bool] = None


@unitypy_define
class BoneInfluence:
    boneIndex_0_: int
    boneIndex_1_: int
    boneIndex_2_: int
    boneIndex_3_: int
    weight_0_: float
    weight_1_: float
    weight_2_: float
    weight_3_: float


@unitypy_define
class BoneWeights4:
    boneIndex_0_: int
    boneIndex_1_: int
    boneIndex_2_: int
    boneIndex_3_: int
    weight_0_: float
    weight_1_: float
    weight_2_: float
    weight_3_: float


@unitypy_define
class BranchWindLevel:
    m_afBend_0: float
    m_afBend_1: float
    m_afBend_10: float
    m_afBend_11: float
    m_afBend_12: float
    m_afBend_13: float
    m_afBend_14: float
    m_afBend_15: float
    m_afBend_16: float
    m_afBend_17: float
    m_afBend_18: float
    m_afBend_19: float
    m_afBend_2: float
    m_afBend_3: float
    m_afBend_4: float
    m_afBend_5: float
    m_afBend_6: float
    m_afBend_7: float
    m_afBend_8: float
    m_afBend_9: float
    m_afFlexibility_0: float
    m_afFlexibility_1: float
    m_afFlexibility_10: float
    m_afFlexibility_11: float
    m_afFlexibility_12: float
    m_afFlexibility_13: float
    m_afFlexibility_14: float
    m_afFlexibility_15: float
    m_afFlexibility_16: float
    m_afFlexibility_17: float
    m_afFlexibility_18: float
    m_afFlexibility_19: float
    m_afFlexibility_2: float
    m_afFlexibility_3: float
    m_afFlexibility_4: float
    m_afFlexibility_5: float
    m_afFlexibility_6: float
    m_afFlexibility_7: float
    m_afFlexibility_8: float
    m_afFlexibility_9: float
    m_afOscillation_0: float
    m_afOscillation_1: float
    m_afOscillation_10: float
    m_afOscillation_11: float
    m_afOscillation_12: float
    m_afOscillation_13: float
    m_afOscillation_14: float
    m_afOscillation_15: float
    m_afOscillation_16: float
    m_afOscillation_17: float
    m_afOscillation_18: float
    m_afOscillation_19: float
    m_afOscillation_2: float
    m_afOscillation_3: float
    m_afOscillation_4: float
    m_afOscillation_5: float
    m_afOscillation_6: float
    m_afOscillation_7: float
    m_afOscillation_8: float
    m_afOscillation_9: float
    m_afSpeed_0: float
    m_afSpeed_1: float
    m_afSpeed_10: float
    m_afSpeed_11: float
    m_afSpeed_12: float
    m_afSpeed_13: float
    m_afSpeed_14: float
    m_afSpeed_15: float
    m_afSpeed_16: float
    m_afSpeed_17: float
    m_afSpeed_18: float
    m_afSpeed_19: float
    m_afSpeed_2: float
    m_afSpeed_3: float
    m_afSpeed_4: float
    m_afSpeed_5: float
    m_afSpeed_6: float
    m_afSpeed_7: float
    m_afSpeed_8: float
    m_afSpeed_9: float
    m_afTurbulence_0: float
    m_afTurbulence_1: float
    m_afTurbulence_10: float
    m_afTurbulence_11: float
    m_afTurbulence_12: float
    m_afTurbulence_13: float
    m_afTurbulence_14: float
    m_afTurbulence_15: float
    m_afTurbulence_16: float
    m_afTurbulence_17: float
    m_afTurbulence_18: float
    m_afTurbulence_19: float
    m_afTurbulence_2: float
    m_afTurbulence_3: float
    m_afTurbulence_4: float
    m_afTurbulence_5: float
    m_afTurbulence_6: float
    m_afTurbulence_7: float
    m_afTurbulence_8: float
    m_afTurbulence_9: float
    m_fIndependence: float


@unitypy_define
class BufferBinding:
    m_Index: int
    m_NameIndex: int
    m_ArraySize: Optional[int] = None


@unitypy_define
class BufferBindingParameter:
    m_ArraySize: int
    m_NameIndex: int
    m_Binding: Optional[Binding] = None
    m_Index: Optional[int] = None
    m_ResourceType: Optional[int] = None


@unitypy_define
class BuildReportFile:
    id: int
    path: str
    role: str
    totalSize: int
    flags: Optional[int] = None


@unitypy_define
class BuildReportPackedAssetInfo:
    classID: int
    fileID: int
    packedSize: int
    sourceAssetGUID: GUID
    buildTimeAssetPath: Optional[str] = None
    offset: Optional[int] = None


@unitypy_define
class BuildReportScenesUsingAsset:
    assetPath: str
    scenePaths: List[str]


@unitypy_define
class BuildStepInfo:
    messages: List[BuildStepMessage]
    stepName: str
    depth: Optional[int] = None
    duration: Optional[int] = None
    durationTicks: Optional[int] = None


@unitypy_define
class BuildStepMessage:
    content: str
    type: int


@unitypy_define
class BuildSummary:
    assetBundleOptions: int
    crc: int
    options: int
    outputPath: str
    platformName: str
    totalErrors: int
    totalSize: int
    totalWarnings: int
    buildContentOptions: Optional[int] = None
    buildGUID: Optional[GUID] = None
    buildManifestHash: Optional[Hash128] = None
    buildName: Optional[str] = None
    buildProfileGuid: Optional[GUID] = None
    buildProfilePath: Optional[str] = None
    buildResult: Optional[int] = None
    buildSessionGUID: Optional[GUID] = None
    buildStartTime: Optional[DateTime] = None
    buildType: Optional[int] = None
    dataPath: Optional[str] = None
    multiProcessEnabled: Optional[bool] = None
    name: Optional[str] = None
    platformGroupName: Optional[str] = None
    subtarget: Optional[int] = None
    success: Optional[bool] = None
    totalTimeMS: Optional[int] = None
    totalTimeTicks: Optional[int] = None


@unitypy_define
class BuildTargetSettings:
    m_BuildTarget: str
    m_TextureFormat: int
    m_AllowsAlphaSplitting: Optional[bool] = None
    m_CompressionQuality: Optional[int] = None
    m_LoadingBehavior: Optional[int] = None
    m_MaxTextureSize: Optional[int] = None
    m_TextureHeight: Optional[int] = None
    m_TextureWidth: Optional[int] = None


@unitypy_define
class BuildTextureStackReference:
    groupName: str
    itemName: str


@unitypy_define
class BuiltAssetBundleInfo:
    bundleArchiveFile: int
    bundleName: str
    packagedFileIndices: List[int]


@unitypy_define
class BuiltinShaderSettings:
    m_Mode: int
    m_Shader: PPtr[Shader]


@unitypy_define
class CGProgram(TextAsset):
    m_Name: str
    m_Script: str
    m_PathName: Optional[str] = None


@unitypy_define
class CachedAssetMetaData:
    guid: GUID
    originalChangeset: int
    originalDigest: Union[Hash128, MdFour]
    originalName: str
    originalParent: GUID
    pathName: str


@unitypy_define
class Channel:
    attributeName: str
    byteOffset: int
    curve: AnimationCurve


@unitypy_define
class ChannelInfo:
    dimension: int
    format: int
    offset: int
    stream: int


@unitypy_define
class CharacterInfo:
    index: int
    uv: Rectf
    vert: Rectf
    advance: Optional[float] = None
    flipped: Optional[bool] = None
    width: Optional[float] = None


@unitypy_define
class Child:
    m_IsAnim: bool
    m_Motion: PPtr[Motion]
    m_Threshold: float
    m_TimeScale: float
    m_CycleOffset: Optional[float] = None
    m_Mirror: Optional[bool] = None
    m_Position: Optional[Vector2f] = None


@unitypy_define
class ChildAnimatorState:
    m_Position: Vector3f
    m_State: PPtr[AnimatorState]


@unitypy_define
class ChildAnimatorStateMachine:
    m_Position: Vector3f
    m_StateMachine: PPtr[AnimatorStateMachine]


@unitypy_define
class ChildMotion:
    m_CycleOffset: float
    m_DirectBlendParameter: str
    m_Mirror: bool
    m_Motion: PPtr[Motion]
    m_Position: Vector2f
    m_Threshold: float
    m_TimeScale: float


@unitypy_define
class ClampVelocityModule:
    dampen: float
    enabled: bool
    magnitude: MinMaxCurve
    separateAxis: bool
    x: MinMaxCurve
    y: MinMaxCurve
    z: MinMaxCurve
    drag: Optional[MinMaxCurve] = None
    inWorldSpace: Optional[bool] = None
    multiplyDragByParticleSize: Optional[bool] = None
    multiplyDragByParticleVelocity: Optional[bool] = None


@unitypy_define
class ClassInfo:
    m_AssemblyNameIndex: int
    m_ClassName: str
    m_IsUnityClass: bool
    m_MethodIndex: int
    m_NamespaceIndex: int
    m_NumOfMethods: int
    m_NamespaceName: Optional[str] = None


@unitypy_define
class ClassMethodInfo:
    m_ClassIndex: int
    m_MethodName: str
    m_OrderNumber: int


@unitypy_define
class Clip:
    m_DenseClip: DenseClip
    m_StreamedClip: StreamedClip
    m_Binding: Optional[OffsetPtr] = None
    m_ConstantClip: Optional[ConstantClip] = None


@unitypy_define
class ClipAnimationInfo:
    firstFrame: Union[float, int]
    lastFrame: Union[float, int]
    loop: bool
    name: str
    wrapMode: int
    additiveReferencePoseFrame: Optional[float] = None
    bodyMask: Optional[List[int]] = None
    curves: Optional[List[ClipAnimationInfoCurve]] = None
    cycleOffset: Optional[float] = None
    events: Optional[List[AnimationEvent]] = None
    hasAdditiveReferencePose: Optional[bool] = None
    heightFromFeet: Optional[bool] = None
    internalID: Optional[int] = None
    keepAdditionalBonesAnimation: Optional[bool] = None
    keepOriginalOrientation: Optional[bool] = None
    keepOriginalPositionXZ: Optional[bool] = None
    keepOriginalPositionY: Optional[bool] = None
    level: Optional[float] = None
    loopBlend: Optional[bool] = None
    loopBlendOrientation: Optional[bool] = None
    loopBlendPositionXZ: Optional[bool] = None
    loopBlendPositionY: Optional[bool] = None
    loopTime: Optional[bool] = None
    maskSource: Optional[PPtr[AvatarMask]] = None
    maskType: Optional[int] = None
    mirror: Optional[bool] = None
    orientationOffsetY: Optional[float] = None
    skeletonMaskElements: Optional[List[AvatarSkeletonMaskElement]] = None
    takeName: Optional[str] = None
    transformMask: Optional[List[TransformMaskElement]] = None


@unitypy_define
class ClipAnimationInfoCurve:
    curve: AnimationCurve
    name: str


@unitypy_define
class ClipMuscleConstant:
    m_AverageAngularSpeed: float
    m_AverageSpeed: Union[float3, float4]
    m_Clip: OffsetPtr
    m_CycleOffset: float
    m_DeltaPose: HumanPose
    m_HeightFromFeet: bool
    m_IndexArray: List[int]
    m_KeepOriginalOrientation: bool
    m_KeepOriginalPositionXZ: bool
    m_KeepOriginalPositionY: bool
    m_LeftFootStartX: xform
    m_Level: float
    m_LoopBlend: bool
    m_LoopBlendOrientation: bool
    m_LoopBlendPositionXZ: bool
    m_LoopBlendPositionY: bool
    m_Mirror: bool
    m_OrientationOffsetY: float
    m_RightFootStartX: xform
    m_StartTime: float
    m_StartX: xform
    m_StopTime: float
    m_ValueArrayDelta: List[ValueDelta]
    m_AdditionalCurveIndexArray: Optional[List[int]] = None
    m_LoopTime: Optional[bool] = None
    m_MotionStartX: Optional[xform] = None
    m_MotionStopX: Optional[xform] = None
    m_StartAtOrigin: Optional[bool] = None
    m_StopX: Optional[xform] = None
    m_ValueArrayReferencePose: Optional[List[float]] = None


@unitypy_define
class ClothAttachment:
    m_Collider: PPtr[Collider]
    m_Tearable: bool
    m_TwoWayInteraction: bool


@unitypy_define
class ClothConstrainCoefficients:
    collisionSphereDistance: float
    maxDistance: float
    collisionSphereRadius: Optional[float] = None
    maxDistanceBias: Optional[float] = None


@unitypy_define
class ClothSphereColliderPair:
    first: PPtr[SphereCollider]
    second: PPtr[SphereCollider]


@unitypy_define
class ClusterInput:
    m_DeviceName: str
    m_Index: int
    m_Name: str
    m_ServerUrl: str
    m_Type: int


@unitypy_define
class CollabEditorSettings:
    inProgressEnabled: bool


@unitypy_define
class Collision(ABC):
    pass


@unitypy_define
class Collision2D(ABC):
    pass


@unitypy_define
class CollisionModule:
    enabled: bool
    minKillSpeed: float
    type: int
    bounce: Optional[float] = None
    colliderForce: Optional[float] = None
    collidesWith: Optional[BitField] = None
    collidesWithDynamic: Optional[bool] = None
    collisionMessages: Optional[bool] = None
    collisionMode: Optional[int] = None
    dampen: Optional[float] = None
    energyLossOnCollision: Optional[float] = None
    interiorCollisions: Optional[bool] = None
    m_Bounce: Optional[MinMaxCurve] = None
    m_Dampen: Optional[MinMaxCurve] = None
    m_EnergyLossOnCollision: Optional[MinMaxCurve] = None
    m_Planes: Optional[List[PPtr[Transform]]] = None
    maxCollisionShapes: Optional[int] = None
    maxKillSpeed: Optional[float] = None
    multiplyColliderForceByCollisionAngle: Optional[bool] = None
    multiplyColliderForceByParticleSize: Optional[bool] = None
    multiplyColliderForceByParticleSpeed: Optional[bool] = None
    particleRadius: Optional[float] = None
    plane0: Optional[PPtr[Transform]] = None
    plane1: Optional[PPtr[Transform]] = None
    plane2: Optional[PPtr[Transform]] = None
    plane3: Optional[PPtr[Transform]] = None
    plane4: Optional[PPtr[Transform]] = None
    plane5: Optional[PPtr[Transform]] = None
    quality: Optional[int] = None
    radiusScale: Optional[float] = None
    voxelSize: Optional[float] = None


@unitypy_define
class ColorBySpeedModule:
    enabled: bool
    gradient: MinMaxGradient
    range: Vector2f


@unitypy_define
class ColorModule:
    enabled: bool
    gradient: MinMaxGradient


@unitypy_define
class ComponentPair:
    component: PPtr[Component]


@unitypy_define
class CompressedAnimationCurve:
    m_Path: str
    m_PostInfinity: int
    m_PreInfinity: int
    m_Slopes: PackedBitVector
    m_Times: PackedBitVector
    m_Values: PackedBitVector


@unitypy_define
class CompressedMesh:
    m_BoneIndices: PackedBitVector
    m_NormalSigns: PackedBitVector
    m_Normals: PackedBitVector
    m_TangentSigns: PackedBitVector
    m_Tangents: PackedBitVector
    m_Triangles: PackedBitVector
    m_UV: PackedBitVector
    m_Vertices: PackedBitVector
    m_Weights: PackedBitVector
    m_BindPoses: Optional[PackedBitVector] = None
    m_Colors: Optional[PackedBitVector] = None
    m_FloatColors: Optional[PackedBitVector] = None
    m_UVInfo: Optional[int] = None


@unitypy_define
class ComputeBufferCounter:
    bindpoint: int
    offset: int


@unitypy_define
class ComputeShaderBuiltinSampler:
    bindPoint: int
    sampler: int


@unitypy_define
class ComputeShaderCB:
    byteSize: int
    name: Union[FastPropertyName, str]
    params: List[ComputeShaderParam]


@unitypy_define
class ComputeShaderKernel:
    builtinSamplers: Union[List[ComputeShaderBuiltinSampler], List[SamplerParameter]]
    cbs: List[ComputeShaderResource]
    code: List[int]
    inBuffers: List[ComputeShaderResource]
    outBuffers: List[ComputeShaderResource]
    textures: List[ComputeShaderResource]
    cbVariantIndices: Optional[List[int]] = None
    name: Optional[Union[FastPropertyName, str]] = None
    requirements: Optional[int] = None
    threadGroupSize: Optional[List[int]] = None


@unitypy_define
class ComputeShaderKernelParent:
    name: str
    dynamicKeywords: Optional[List[str]] = None
    globalKeywords: Optional[List[str]] = None
    localKeywords: Optional[List[str]] = None
    uniqueVariants: Optional[List[ComputeShaderKernel]] = None
    validKeywords: Optional[List[str]] = None
    variantIndices: Optional[List[Tuple[str, int]]] = None
    variantMap: Optional[List[Tuple[str, ComputeShaderKernel]]] = None


@unitypy_define
class ComputeShaderParam:
    arraySize: int
    colCount: int
    name: Union[FastPropertyName, str]
    offset: int
    rowCount: int
    type: int


@unitypy_define
class ComputeShaderPlatformVariant:
    constantBuffers: List[ComputeShaderCB]
    kernels: List[ComputeShaderKernelParent]
    resourcesResolved: bool
    targetLevel: int
    targetRenderer: int


@unitypy_define
class ComputeShaderResource:
    name: Union[FastPropertyName, str]
    bindPoint: Optional[int] = None
    counter: Optional[ComputeBufferCounter] = None
    generatedName: Optional[Union[FastPropertyName, str]] = None
    m_Binding: Optional[Binding] = None
    m_SamplerBinding: Optional[Binding] = None
    resType: Optional[int] = None
    samplerBindPoint: Optional[int] = None
    secondaryBindPoint: Optional[int] = None
    texDimension: Optional[int] = None


@unitypy_define
class ComputeShaderVariant:
    constantBuffers: List[ComputeShaderCB]
    kernels: List[ComputeShaderKernel]
    targetLevel: int
    targetRenderer: int
    resourcesResolved: Optional[bool] = None


@unitypy_define
class Condition:
    m_ConditionEvent: str
    m_ConditionMode: int
    m_EventTreshold: float
    m_ExitTime: float


@unitypy_define
class ConditionConstant:
    m_ConditionMode: int
    m_EventID: int
    m_EventThreshold: float
    m_ExitTime: float


@unitypy_define
class ConfigSetting:
    flags: int
    value: str


@unitypy_define
class ConstantBuffer:
    m_MatrixParams: List[MatrixParameter]
    m_NameIndex: int
    m_Size: int
    m_VectorParams: List[VectorParameter]
    m_IsPartialCB: Optional[bool] = None
    m_StructParams: Optional[List[StructParameter]] = None


@unitypy_define
class ConstantBufferParameter:
    m_IsPartialCB: bool
    m_MatrixParams: List[MatrixParameter]
    m_NameIndex: int
    m_Size: int
    m_StructParams: List[StructParameter]
    m_VectorParams: List[VectorParameter]


@unitypy_define
class ConstantClip:
    data: List[float]


@unitypy_define
class ConstraintSource:
    sourceTransform: PPtr[Transform]
    weight: float


@unitypy_define
class ControllerConstant:
    m_DefaultValues: OffsetPtr
    m_StateMachineArray: List[OffsetPtr]
    m_Values: OffsetPtr
    m_HumanLayerArray: Optional[List[OffsetPtr]] = None
    m_LayerArray: Optional[List[OffsetPtr]] = None


@unitypy_define
class CrashReportingSettings:
    m_EventUrl: str
    m_EnableCloudDiagnosticsReporting: Optional[bool] = None
    m_Enabled: Optional[bool] = None
    m_LogBufferSize: Optional[int] = None
    m_NativeEventUrl: Optional[str] = None


@unitypy_define
class CustomDataModule:
    color0: MinMaxGradient
    color1: MinMaxGradient
    enabled: bool
    mode0: int
    mode1: int
    vector0_0: MinMaxCurve
    vector0_1: MinMaxCurve
    vector0_2: MinMaxCurve
    vector0_3: MinMaxCurve
    vector1_0: MinMaxCurve
    vector1_1: MinMaxCurve
    vector1_2: MinMaxCurve
    vector1_3: MinMaxCurve
    vectorComponentCount0: int
    vectorComponentCount1: int


@unitypy_define
class D3D12DeviceFilterData:
    deviceName: str
    deviceType: int
    driverVersion: str
    driverVersionComparator: int
    featureLevel: str
    featureLevelComparator: int
    graphicsMemory: str
    graphicsMemoryComparator: int
    processorCount: str
    processorCountComparator: int
    vendorName: str


@unitypy_define
class D3D12GraphicsJobsDeviceFilterData:
    filter: D3D12DeviceFilterData
    preferredMode: int


@unitypy_define
class DataTemplate(NamedObject):
    m_Father: PPtr[DataTemplate]
    m_IsDataTemplate: bool
    m_LastMergeIdentifier: GUID
    m_Name: str
    m_Objects: List[PPtr[EditorExtension]]


@unitypy_define
class DateTime:
    ticks: int


@unitypy_define
class DefaultPreset:
    m_Preset: PPtr[Preset]
    m_Disabled: Optional[bool] = None
    m_Filter: Optional[str] = None


@unitypy_define
class DefaultPresetList:
    defaultPresets: List[DefaultPreset]
    type: PresetType


@unitypy_define
class DeletedItem:
    changeset: int
    digest: Union[Hash128, MdFour]
    fullPath: str
    guid: GUID
    parent: GUID
    type: int


@unitypy_define
class DenseClip:
    m_BeginTime: float
    m_CurveCount: int
    m_FrameCount: int
    m_SampleArray: List[float]
    m_SampleRate: float


@unitypy_define
class DetailDatabase:
    WavingGrassTint: ColorRGBA
    m_DetailPrototypes: List[DetailPrototype]
    m_PatchCount: int
    m_PatchSamples: int
    m_Patches: List[DetailPatch]
    m_PreloadTextureAtlasData: List[PPtr[Texture2D]]
    m_TreeInstances: List[TreeInstance]
    m_TreePrototypes: List[TreePrototype]
    m_WavingGrassAmount: float
    m_WavingGrassSpeed: float
    m_WavingGrassStrength: float
    m_DefaultShaders_0_: Optional[PPtr[Shader]] = None
    m_DefaultShaders_1_: Optional[PPtr[Shader]] = None
    m_DefaultShaders_2_: Optional[PPtr[Shader]] = None
    m_DetailBillboardShader: Optional[PPtr[Shader]] = None
    m_DetailMeshGrassShader: Optional[PPtr[Shader]] = None
    m_DetailMeshLitShader: Optional[PPtr[Shader]] = None
    m_DetailScatterMode: Optional[int] = None
    m_RandomRotations: Optional[List[Vector3f]] = None


@unitypy_define
class DetailPatch:
    layerIndices: List[int]
    bounds: Optional[AABB] = None
    coverage: Optional[List[int]] = None
    numberOfObjects: Optional[List[int]] = None


@unitypy_define
class DetailPrototype:
    dryColor: ColorRGBA
    healthyColor: ColorRGBA
    maxHeight: float
    maxWidth: float
    minHeight: float
    minWidth: float
    noiseSpread: float
    prototype: PPtr[GameObject]
    prototypeTexture: PPtr[Texture2D]
    renderMode: int
    usePrototypeMesh: int
    alignToGround: Optional[float] = None
    bendFactor: Optional[float] = None
    density: Optional[float] = None
    holeTestRadius: Optional[float] = None
    lightmapFactor: Optional[float] = None
    noiseSeed: Optional[int] = None
    positionJitter: Optional[float] = None
    positionOrderliness: Optional[float] = None
    targetCoverage: Optional[float] = None
    useDensityScaling: Optional[int] = None
    useInstancing: Optional[int] = None


@unitypy_define
class DeviceNone:
    pass


@unitypy_define
class DirectorGenericBinding:
    key: PPtr[Object]
    value: PPtr[Object]


@unitypy_define
class DirectorPlayer(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class EffectConstant:
    bypass: bool
    groupConstantIndex: int
    parameterIndices: List[int]
    prevEffectIndex: int
    sendTargetEffectIndex: int
    type: int
    wetMixLevelIndex: int


@unitypy_define
class EmbeddedNativeType:
    m_FloatArray: List[float]
    m_String: str


