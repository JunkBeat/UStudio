# type: ignore
from __future__ import annotations

from ._common import ABC, unitypy_define
from ._part00 import Component, EditorExtension
from ._part01 import Renderer


@unitypy_define
class UIRenderer(Renderer):
    m_GameObject: PPtr[GameObject]
    m_CastShadows: Optional[int] = None
    m_DynamicOccludee: Optional[int] = None
    m_Enabled: Optional[bool] = None
    m_ForceMeshLod: Optional[int] = None
    m_LightProbeUsage: Optional[int] = None
    m_LightProbeVolumeOverride: Optional[PPtr[GameObject]] = None
    m_LightmapIndex: Optional[int] = None
    m_LightmapIndexDynamic: Optional[int] = None
    m_LightmapTilingOffset: Optional[Vector4f] = None
    m_LightmapTilingOffsetDynamic: Optional[Vector4f] = None
    m_MaskInteraction: Optional[int] = None
    m_Materials: Optional[List[PPtr[Material]]] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_MotionVectors: Optional[int] = None
    m_ProbeAnchor: Optional[PPtr[Transform]] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_ReceiveShadows: Optional[int] = None
    m_ReflectionProbeUsage: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_SortingOrder: Optional[int] = None
    m_StaticBatchInfo: Optional[StaticBatchInfo] = None
    m_StaticBatchRoot: Optional[PPtr[Transform]] = None
    m_StaticShadowCaster: Optional[int] = None


@unitypy_define
class VFXRenderer(Renderer):
    m_CastShadows: int
    m_DynamicOccludee: int
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightProbeUsage: int
    m_LightProbeVolumeOverride: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapIndexDynamic: int
    m_LightmapTilingOffset: Vector4f
    m_LightmapTilingOffsetDynamic: Vector4f
    m_MotionVectors: int
    m_ProbeAnchor: PPtr[Transform]
    m_ReceiveShadows: int
    m_ReflectionProbeUsage: int
    m_RendererPriority: int
    m_RenderingLayerMask: int
    m_SortingLayer: int
    m_SortingLayerID: int
    m_SortingOrder: int
    m_StaticBatchInfo: StaticBatchInfo
    m_StaticBatchRoot: PPtr[Transform]
    m_ForceMeshLod: Optional[int] = None
    m_MaskInteraction: Optional[int] = None
    m_Materials: Optional[List[PPtr[Material]]] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_SmallMeshCulling: Optional[int] = None
    m_StaticShadowCaster: Optional[int] = None


@unitypy_define
class Rigidbody(Component):
    m_CollisionDetection: int
    m_Constraints: int
    m_GameObject: PPtr[GameObject]
    m_Interpolate: int
    m_IsKinematic: bool
    m_Mass: float
    m_UseGravity: bool
    m_AngularDamping: Optional[float] = None
    m_AngularDrag: Optional[float] = None
    m_CenterOfMass: Optional[Vector3f] = None
    m_Drag: Optional[float] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ImplicitCom: Optional[bool] = None
    m_ImplicitTensor: Optional[bool] = None
    m_IncludeLayers: Optional[BitField] = None
    m_InertiaRotation: Optional[Quaternionf] = None
    m_InertiaTensor: Optional[Vector3f] = None
    m_LinearDamping: Optional[float] = None


@unitypy_define
class Rigidbody2D(Component):
    m_CollisionDetection: int
    m_GameObject: PPtr[GameObject]
    m_GravityScale: float
    m_Interpolate: int
    m_Mass: float
    m_SleepingMode: int
    m_AngularDamping: Optional[float] = None
    m_AngularDrag: Optional[float] = None
    m_BodyType: Optional[int] = None
    m_Constraints: Optional[int] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_FixedAngle: Optional[bool] = None
    m_IncludeLayers: Optional[BitField] = None
    m_IsKinematic: Optional[bool] = None
    m_LinearDamping: Optional[float] = None
    m_LinearDrag: Optional[float] = None
    m_Material: Optional[PPtr[PhysicsMaterial2D]] = None
    m_Simulated: Optional[bool] = None
    m_UseAutoMass: Optional[bool] = None
    m_UseFullKinematicContacts: Optional[bool] = None


@unitypy_define
class TextMesh(Component):
    m_Alignment: int
    m_Anchor: int
    m_CharacterSize: float
    m_Font: PPtr[Font]
    m_FontSize: int
    m_FontStyle: int
    m_GameObject: PPtr[GameObject]
    m_LineSpacing: float
    m_OffsetZ: float
    m_TabSize: float
    m_Text: str
    m_Color: Optional[ColorRGBA] = None
    m_RichText: Optional[bool] = None


@unitypy_define
class Transform(Component):
    m_Children: List[PPtr[Transform]]
    m_Father: PPtr[Transform]
    m_GameObject: PPtr[GameObject]
    m_LocalPosition: Vector3f
    m_LocalRotation: Quaternionf
    m_LocalScale: Vector3f


@unitypy_define
class RectTransform(Transform):
    m_AnchorMax: Vector2f
    m_AnchorMin: Vector2f
    m_GameObject: PPtr[GameObject]
    m_Pivot: Vector2f
    m_SizeDelta: Vector2f
    m_AnchoredPosition: Optional[Vector2f] = None
    m_Children: Optional[List[PPtr[Transform]]] = None
    m_Father: Optional[PPtr[Transform]] = None
    m_LocalPosition: Optional[Vector3f] = None
    m_LocalRotation: Optional[Quaternionf] = None
    m_LocalScale: Optional[Vector3f] = None
    m_Position: Optional[Vector2f] = None


@unitypy_define
class Tree(Component):
    m_GameObject: PPtr[GameObject]
    m_SpeedTreeWindAsset: Optional[PPtr[SpeedTreeWindAsset]] = None


@unitypy_define
class WorldAnchor(Component):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class WorldParticleCollider(Component):
    m_BounceFactor: float
    m_CollidesWith: BitField
    m_CollisionEnergyLoss: float
    m_GameObject: PPtr[GameObject]
    m_MinKillVelocity: float
    m_SendCollisionMessage: bool


@unitypy_define
class GameObject(EditorExtension):
    m_Component: Union[List[ComponentPair], List[Tuple[int, PPtr[Component]]]]
    m_IsActive: Union[bool, int]
    m_Layer: int
    m_Name: str
    m_Tag: int


@unitypy_define
class NamedObject(EditorExtension, ABC):
    pass


@unitypy_define
class AnimatorState(NamedObject):
    m_CycleOffset: float
    m_IKOnFeet: bool
    m_Mirror: bool
    m_Motion: PPtr[Motion]
    m_Name: str
    m_Position: Vector3f
    m_Speed: float
    m_StateMachineBehaviours: List[PPtr[MonoBehaviour]]
    m_Tag: str
    m_Transitions: List[PPtr[AnimatorStateTransition]]
    m_WriteDefaultValues: bool
    m_CycleOffsetParameter: Optional[str] = None
    m_CycleOffsetParameterActive: Optional[bool] = None
    m_MirrorParameter: Optional[str] = None
    m_MirrorParameterActive: Optional[bool] = None
    m_SpeedParameter: Optional[str] = None
    m_SpeedParameterActive: Optional[bool] = None
    m_TimeParameter: Optional[str] = None
    m_TimeParameterActive: Optional[bool] = None


@unitypy_define
class AnimatorStateMachine(NamedObject):
    m_AnyStatePosition: Vector3f
    m_AnyStateTransitions: List[PPtr[AnimatorStateTransition]]
    m_ChildStateMachines: List[ChildAnimatorStateMachine]
    m_ChildStates: List[ChildAnimatorState]
    m_DefaultState: PPtr[AnimatorState]
    m_EntryPosition: Vector3f
    m_EntryTransitions: List[PPtr[AnimatorTransition]]
    m_ExitPosition: Vector3f
    m_Name: str
    m_ParentStateMachinePosition: Vector3f
    m_StateMachineBehaviours: List[PPtr[MonoBehaviour]]
    m_StateMachineTransitions: List[Tuple[PPtr[AnimatorStateMachine], List[PPtr[AnimatorTransition]]]]


@unitypy_define
class AnimatorTransitionBase(NamedObject):
    m_Conditions: List[AnimatorCondition]
    m_DstState: PPtr[AnimatorState]
    m_DstStateMachine: PPtr[AnimatorStateMachine]
    m_IsExit: bool
    m_Mute: bool
    m_Name: str
    m_Solo: bool


@unitypy_define
class AnimatorStateTransition(AnimatorTransitionBase):
    m_CanTransitionToSelf: bool
    m_Conditions: List[AnimatorCondition]
    m_DstState: PPtr[AnimatorState]
    m_DstStateMachine: PPtr[AnimatorStateMachine]
    m_ExitTime: float
    m_HasExitTime: bool
    m_InterruptionSource: int
    m_IsExit: bool
    m_Mute: bool
    m_Name: str
    m_OrderedInterruption: bool
    m_Solo: bool
    m_TransitionDuration: float
    m_TransitionOffset: float
    m_HasFixedDuration: Optional[bool] = None


@unitypy_define
class AnimatorTransition(AnimatorTransitionBase):
    m_Conditions: List[AnimatorCondition]
    m_DstState: PPtr[AnimatorState]
    m_DstStateMachine: PPtr[AnimatorStateMachine]
    m_IsExit: bool
    m_Mute: bool
    m_Name: str
    m_Solo: bool


@unitypy_define
class AssetBundle(NamedObject):
    m_Container: List[Tuple[str, AssetInfo]]
    m_MainAsset: AssetInfo
    m_Name: str
    m_PreloadTable: List[PPtr[Object]]
    m_AssetBundleName: Optional[str] = None
    m_ClassCompatibility: Optional[List[Tuple[int, int]]] = None
    m_ClassVersionMap: Optional[List[Tuple[int, int]]] = None
    m_Dependencies: Optional[List[str]] = None
    m_ExplicitDataLayout: Optional[int] = None
    m_IsStreamedSceneAssetBundle: Optional[bool] = None
    m_PathFlags: Optional[int] = None
    m_RuntimeCompatibility: Optional[int] = None
    m_SceneHashes: Optional[List[Tuple[str, str]]] = None
    m_ScriptCompatibility: Optional[List[AssetBundleScriptInfo]] = None


@unitypy_define
class AssetBundleManifest(NamedObject):
    AssetBundleInfos: List[Tuple[int, AssetBundleInfo]]
    AssetBundleNames: List[Tuple[int, str]]
    AssetBundlesWithVariant: List[int]
    m_Name: str


@unitypy_define
class AssetImportInProgressProxy(NamedObject):
    m_Name: str


@unitypy_define
class AssetImporter(NamedObject, ABC):
    pass


@unitypy_define
class ASTCImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_Name: str
    m_UserData: str


@unitypy_define
class AndroidAssetPackImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class AssemblyDefinitionImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UserData: str
    m_UsedFileIDs: Optional[List[int]] = None


@unitypy_define
class AssemblyDefinitionReferenceImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class AudioImporter(AssetImporter):
    m_3D: bool
    m_ForceToMono: bool
    m_Name: str
    audio_preview_data: Optional[bytes] = None
    m_Ambisonic: Optional[bool] = None
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_DefaultSettings: Optional[SampleSettings] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_Format: Optional[int] = None
    m_LoadInBackground: Optional[bool] = None
    m_Loopable: Optional[bool] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_Normalize: Optional[bool] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_Output: Optional[Union[AudioImporterOutput, Output]] = None
    m_PlatformSettingOverrides: Optional[Union[List[Tuple[int, SampleSettings]], List[Tuple[str, SampleSettings]]]] = None
    m_PreloadAudioData: Optional[bool] = None
    m_PreviewData: Optional[PreviewData] = None
    m_PreviewDataLength: Optional[int] = None
    m_Quality: Optional[float] = None
    m_Stream: Optional[int] = None
    m_UseHardware: Optional[bool] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class BlockShaderImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_EmbedBlocksInGeneratedShader: bool
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class BuildArchiveImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class BuildInstructionImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class BuildMetaDataImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class C4DImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class ComputeShaderImporter(AssetImporter):
    m_Name: str
    m_UserData: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_CurrentAPIMask: Optional[int] = None
    m_CurrentBuildTarget: Optional[int] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_PreprocessorOverride: Optional[int] = None
    m_UsedFileIDs: Optional[List[int]] = None


@unitypy_define
class DDSImporter(AssetImporter):
    m_Name: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_IsReadable: Optional[bool] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UserData: Optional[str] = None


@unitypy_define
class DefaultImporter(AssetImporter):
    m_Name: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class IHVImageFormatImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_IsReadable: bool
    m_Name: str
    m_TextureSettings: GLTextureSettings
    m_UserData: str
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_IgnoreMipmapLimit: Optional[bool] = None
    m_MipmapLimitGroupName: Optional[str] = None
    m_StreamingMipmaps: Optional[bool] = None
    m_StreamingMipmapsPriority: Optional[int] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_sRGBTexture: Optional[bool] = None


@unitypy_define
class KTXImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_Name: str
    m_UserData: str


@unitypy_define
class LibraryAssetImporter(AssetImporter):
    m_Name: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class LocalizationImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UserData: str
    m_UsedFileIDs: Optional[List[int]] = None


@unitypy_define
class ModelImporter(AssetImporter, ABC):
    pass


@unitypy_define
class FBXImporter(ModelImporter):
    m_AddColliders: bool
    m_AnimationCompression: int
    m_AnimationPositionError: float
    m_AnimationRotationError: float
    m_AnimationScaleError: float
    m_AnimationWrapMode: int
    m_BakeSimulation: bool
    m_ClipAnimations: List[ClipAnimationInfo]
    m_GlobalScale: float
    m_HasExtraRoot: bool
    m_ImportedRoots: List[PPtr[GameObject]]
    m_MeshCompression: int
    m_Name: str
    m_UseFileUnits: bool
    normalSmoothAngle: float
    bakeAxisConversion: Optional[bool] = None
    blendShapeNormalImportMode: Optional[int] = None
    calculateBlendshapeNormalsDeltaFromImportedNormals: Optional[bool] = None
    generateMeshLods: Optional[bool] = None
    generateSecondaryUV: Optional[bool] = None
    importUVs: Optional[int] = None
    importVertexColors: Optional[bool] = None
    indexFormat: Optional[int] = None
    keepQuads: Optional[bool] = None
    legacyComputeAllNormalsFromSmoothingGroupsWhenMeshHasBlendShapes: Optional[bool] = None
    m_AddHumanoidExtraRootOnlyWhenUsingAvatar: Optional[bool] = None
    m_AdditionalBone: Optional[bool] = None
    m_AnimationDoRetargetingWarnings: Optional[bool] = None
    m_AnimationImportErrors: Optional[str] = None
    m_AnimationImportWarnings: Optional[str] = None
    m_AnimationRetargetingWarnings: Optional[str] = None
    m_AnimationType: Optional[int] = None
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_AutoGenerateAvatarMappingIfUnspecified: Optional[bool] = None
    m_AutoMapExternalMaterials: Optional[bool] = None
    m_AvatarSetup: Optional[int] = None
    m_ContainsAnimation: Optional[bool] = None
    m_CopyAvatar: Optional[bool] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_ExtraExposedTransformPaths: Optional[List[str]] = None
    m_ExtraUserProperties: Optional[List[str]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_FileIdsGeneration: Optional[int] = None
    m_FileScale: Optional[float] = None
    m_FileScaleFactor: Optional[float] = None
    m_FileScaleUnit: Optional[str] = None
    m_FirstImportVersion: Optional[int] = None
    m_GenerateAnimations: Optional[int] = None
    m_GenerateMaterials: Optional[int] = None
    m_HasEmbeddedTextures: Optional[bool] = None
    m_HasPreviousCalculatedGlobalScale: Optional[bool] = None
    m_HumanDescription: Optional[HumanDescription] = None
    m_HumanoidOversampling: Optional[int] = None
    m_ImportAnimatedCustomProperties: Optional[bool] = None
    m_ImportAnimation: Optional[bool] = None
    m_ImportBlendShapeDeformPercent: Optional[bool] = None
    m_ImportBlendShapes: Optional[bool] = None
    m_ImportCameras: Optional[bool] = None
    m_ImportConstraints: Optional[bool] = None
    m_ImportLights: Optional[bool] = None
    m_ImportMaterials: Optional[bool] = None
    m_ImportPhysicalCameras: Optional[bool] = None
    m_ImportVisibility: Optional[bool] = None
    m_ImportedTakeInfos: Optional[List[TakeInfo]] = None
    m_InternalIDToNameTable: Optional[List[Tuple[Tuple[int, int], str]]] = None
    m_IsReadable: Optional[bool] = None
    m_LODScreenPercentages: Optional[List[float]] = None
    m_LastHumanDescriptionAvatarSource: Optional[PPtr[Avatar]] = None
    m_LegacyGenerateAnimations: Optional[int] = None
    m_MaterialImportMode: Optional[int] = None
    m_MaterialLocation: Optional[int] = None
    m_MaterialName: Optional[int] = None
    m_MaterialSearch: Optional[int] = None
    m_Materials: Optional[List[SourceAssetIdentifier]] = None
    m_MeshSettings_generateSecondaryUV: Optional[bool] = None
    m_MeshSettings_normalImportMode: Optional[int] = None
    m_MeshSettings_secondaryUVAngleDistortion: Optional[float] = None
    m_MeshSettings_secondaryUVAreaDistortion: Optional[float] = None
    m_MeshSettings_secondaryUVHardAngle: Optional[float] = None
    m_MeshSettings_secondaryUVPackMargin: Optional[float] = None
    m_MeshSettings_swapUVChannels: Optional[bool] = None
    m_MeshSettings_tangentImportMode: Optional[int] = None
    m_MotionNodeName: Optional[str] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_NodeNameCollisionStrategy: Optional[int] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_OptimizeGameObjects: Optional[bool] = None
    m_PreBakeConvexCollisionMesh: Optional[bool] = None
    m_PreBakeTriangleCollisionMesh: Optional[bool] = None
    m_PreserveHierarchy: Optional[bool] = None
    m_PreviousCalculatedGlobalScale: Optional[float] = None
    m_ReferencedClips: Optional[List[GUID]] = None
    m_RemapMaterialsIfMaterialImportModeIsNone: Optional[bool] = None
    m_RemoveConstantScaleCurves: Optional[bool] = None
    m_ResampleCurves: Optional[bool] = None
    m_ResampleRotations: Optional[bool] = None
    m_RigImportErrors: Optional[str] = None
    m_RigImportWarnings: Optional[str] = None
    m_SearchTexturesGlobally: Optional[bool] = None
    m_SortHierarchyByName: Optional[bool] = None
    m_SplitAnimations: Optional[bool] = None
    m_StrictVertexDataChecks: Optional[bool] = None
    m_SupportsEmbeddedMaterials: Optional[bool] = None
    m_UseFileScale: Optional[bool] = None
    m_UseSRGBMaterialColor: Optional[bool] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None
    maxBonesPerVertex: Optional[int] = None
    maximumMeshLod: Optional[int] = None
    meshLodGenerationFlags: Optional[int] = None
    meshOptimizationFlags: Optional[int] = None
    minBoneWeight: Optional[float] = None
    normalCalculationMode: Optional[int] = None
    normalImportMode: Optional[int] = None
    normalSmoothingSource: Optional[int] = None
    optimizeBones: Optional[bool] = None
    optimizeMesh: Optional[bool] = None
    optimizeMeshForGPU: Optional[bool] = None
    secondaryUVAngleDistortion: Optional[float] = None
    secondaryUVAreaDistortion: Optional[float] = None
    secondaryUVHardAngle: Optional[float] = None
    secondaryUVMarginMethod: Optional[int] = None
    secondaryUVMinLightmapResolution: Optional[float] = None
    secondaryUVMinObjectScale: Optional[float] = None
    secondaryUVPackMargin: Optional[float] = None
    skinWeightsMode: Optional[int] = None
    splitTangentsAcrossUV: Optional[bool] = None
    swapUVChannels: Optional[bool] = None
    tangentImportMode: Optional[int] = None
    weldVertices: Optional[bool] = None


@unitypy_define
class Mesh3DSImporter(ModelImporter):
    m_AddColliders: bool
    m_AnimationCompression: int
    m_AnimationPositionError: float
    m_AnimationRotationError: float
    m_AnimationScaleError: float
    m_AnimationWrapMode: int
    m_BakeSimulation: bool
    m_ClipAnimations: List[ClipAnimationInfo]
    m_GlobalScale: float
    m_HasExtraRoot: bool
    m_ImportedRoots: List[PPtr[GameObject]]
    m_MeshCompression: int
    m_Name: str
    m_UseFileUnits: bool
    normalSmoothAngle: float
    bakeAxisConversion: Optional[bool] = None
    blendShapeNormalImportMode: Optional[int] = None
    calculateBlendshapeNormalsDeltaFromImportedNormals: Optional[bool] = None
    generateMeshLods: Optional[bool] = None
    generateSecondaryUV: Optional[bool] = None
    importUVs: Optional[int] = None
    importVertexColors: Optional[bool] = None
    indexFormat: Optional[int] = None
    keepQuads: Optional[bool] = None
    legacyComputeAllNormalsFromSmoothingGroupsWhenMeshHasBlendShapes: Optional[bool] = None
    m_AddHumanoidExtraRootOnlyWhenUsingAvatar: Optional[bool] = None
    m_AdditionalBone: Optional[bool] = None
    m_AnimationDoRetargetingWarnings: Optional[bool] = None
    m_AnimationImportErrors: Optional[str] = None
    m_AnimationImportWarnings: Optional[str] = None
    m_AnimationRetargetingWarnings: Optional[str] = None
    m_AnimationType: Optional[int] = None
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_AutoGenerateAvatarMappingIfUnspecified: Optional[bool] = None
    m_AutoMapExternalMaterials: Optional[bool] = None
    m_AvatarSetup: Optional[int] = None
    m_ContainsAnimation: Optional[bool] = None
    m_CopyAvatar: Optional[bool] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_ExtraExposedTransformPaths: Optional[List[str]] = None
    m_ExtraUserProperties: Optional[List[str]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_FileIdsGeneration: Optional[int] = None
    m_FileScale: Optional[float] = None
    m_FileScaleFactor: Optional[float] = None
    m_FileScaleUnit: Optional[str] = None
    m_FirstImportVersion: Optional[int] = None
    m_GenerateAnimations: Optional[int] = None
    m_GenerateMaterials: Optional[int] = None
    m_HasEmbeddedTextures: Optional[bool] = None
    m_HasPreviousCalculatedGlobalScale: Optional[bool] = None
    m_HumanDescription: Optional[HumanDescription] = None
    m_HumanoidOversampling: Optional[int] = None
    m_ImportAnimatedCustomProperties: Optional[bool] = None
    m_ImportAnimation: Optional[bool] = None
    m_ImportBlendShapeDeformPercent: Optional[bool] = None
    m_ImportBlendShapes: Optional[bool] = None
    m_ImportCameras: Optional[bool] = None
    m_ImportConstraints: Optional[bool] = None
    m_ImportLights: Optional[bool] = None
    m_ImportMaterials: Optional[bool] = None
    m_ImportPhysicalCameras: Optional[bool] = None
    m_ImportVisibility: Optional[bool] = None
    m_ImportedTakeInfos: Optional[List[TakeInfo]] = None
    m_InternalIDToNameTable: Optional[List[Tuple[Tuple[int, int], str]]] = None
    m_IsReadable: Optional[bool] = None
    m_LODScreenPercentages: Optional[List[float]] = None
    m_LastHumanDescriptionAvatarSource: Optional[PPtr[Avatar]] = None
    m_LegacyGenerateAnimations: Optional[int] = None
    m_MaterialImportMode: Optional[int] = None
    m_MaterialLocation: Optional[int] = None
    m_MaterialName: Optional[int] = None
    m_MaterialSearch: Optional[int] = None
    m_Materials: Optional[List[SourceAssetIdentifier]] = None
    m_MeshSettings_generateSecondaryUV: Optional[bool] = None
    m_MeshSettings_normalImportMode: Optional[int] = None
    m_MeshSettings_secondaryUVAngleDistortion: Optional[float] = None
    m_MeshSettings_secondaryUVAreaDistortion: Optional[float] = None
    m_MeshSettings_secondaryUVHardAngle: Optional[float] = None
    m_MeshSettings_secondaryUVPackMargin: Optional[float] = None
    m_MeshSettings_swapUVChannels: Optional[bool] = None
    m_MeshSettings_tangentImportMode: Optional[int] = None
    m_MotionNodeName: Optional[str] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_NodeNameCollisionStrategy: Optional[int] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_OptimizeGameObjects: Optional[bool] = None
    m_PreBakeConvexCollisionMesh: Optional[bool] = None
    m_PreBakeTriangleCollisionMesh: Optional[bool] = None
    m_PreserveHierarchy: Optional[bool] = None
    m_PreviousCalculatedGlobalScale: Optional[float] = None
    m_ReferencedClips: Optional[List[GUID]] = None
    m_RemapMaterialsIfMaterialImportModeIsNone: Optional[bool] = None
    m_RemoveConstantScaleCurves: Optional[bool] = None
    m_ResampleCurves: Optional[bool] = None
    m_ResampleRotations: Optional[bool] = None
    m_RigImportErrors: Optional[str] = None
    m_RigImportWarnings: Optional[str] = None
    m_SearchTexturesGlobally: Optional[bool] = None
    m_SortHierarchyByName: Optional[bool] = None
    m_SplitAnimations: Optional[bool] = None
    m_StrictVertexDataChecks: Optional[bool] = None
    m_SupportsEmbeddedMaterials: Optional[bool] = None
    m_UseFileScale: Optional[bool] = None
    m_UseSRGBMaterialColor: Optional[bool] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None
    maxBonesPerVertex: Optional[int] = None
    maximumMeshLod: Optional[int] = None
    meshLodGenerationFlags: Optional[int] = None
    meshOptimizationFlags: Optional[int] = None
    minBoneWeight: Optional[float] = None
    normalCalculationMode: Optional[int] = None
    normalImportMode: Optional[int] = None
    normalSmoothingSource: Optional[int] = None
    optimizeBones: Optional[bool] = None
    optimizeMesh: Optional[bool] = None
    optimizeMeshForGPU: Optional[bool] = None
    secondaryUVAngleDistortion: Optional[float] = None
    secondaryUVAreaDistortion: Optional[float] = None
    secondaryUVHardAngle: Optional[float] = None
    secondaryUVMarginMethod: Optional[int] = None
    secondaryUVMinLightmapResolution: Optional[float] = None
    secondaryUVMinObjectScale: Optional[float] = None
    secondaryUVPackMargin: Optional[float] = None
    skinWeightsMode: Optional[int] = None
    splitTangentsAcrossUV: Optional[bool] = None
    swapUVChannels: Optional[bool] = None
    tangentImportMode: Optional[int] = None
    weldVertices: Optional[bool] = None


@unitypy_define
class SketchUpImporter(ModelImporter):
    generateSecondaryUV: bool
    keepQuads: bool
    m_AddColliders: bool
    m_AdditionalBone: bool
    m_AnimationCompression: int
    m_AnimationDoRetargetingWarnings: bool
    m_AnimationImportErrors: str
    m_AnimationImportWarnings: str
    m_AnimationPositionError: float
    m_AnimationRetargetingWarnings: str
    m_AnimationRotationError: float
    m_AnimationScaleError: float
    m_AnimationType: int
    m_AnimationWrapMode: int
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_AssetHash: Hash128
    m_BakeSimulation: bool
    m_ClipAnimations: List[ClipAnimationInfo]
    m_ExtraExposedTransformPaths: List[str]
    m_FileScale: float
    m_FileUnit: int
    m_GenerateBackFace: bool
    m_GlobalScale: float
    m_HasExtraRoot: bool
    m_HumanDescription: HumanDescription
    m_ImportAnimation: bool
    m_ImportBlendShapes: bool
    m_ImportedRoots: List[PPtr[GameObject]]
    m_ImportedTakeInfos: List[TakeInfo]
    m_IsReadable: bool
    m_LODScreenPercentages: List[float]
    m_LastHumanDescriptionAvatarSource: PPtr[Avatar]
    m_Latitude: float
    m_LegacyGenerateAnimations: int
    m_Longitude: float
    m_MaterialName: int
    m_MaterialSearch: int
    m_MergeCoplanarFaces: bool
    m_MeshCompression: int
    m_MotionNodeName: str
    m_Name: str
    m_NorthCorrection: float
    m_OptimizeGameObjects: bool
    m_ReferencedClips: List[GUID]
    m_SelectedNodes: List[int]
    m_SketchUpImportData: SketchUpImportData
    m_UseFileScale: bool
    m_UseFileUnits: bool
    m_UserData: str
    normalImportMode: int
    normalSmoothAngle: float
    secondaryUVAngleDistortion: float
    secondaryUVAreaDistortion: float
    secondaryUVHardAngle: float
    secondaryUVPackMargin: float
    swapUVChannels: bool
    tangentImportMode: int
    weldVertices: bool
    bakeAxisConversion: Optional[bool] = None
    blendShapeNormalImportMode: Optional[int] = None
    calculateBlendshapeNormalsDeltaFromImportedNormals: Optional[bool] = None
    generateMeshLods: Optional[bool] = None
    importUVs: Optional[int] = None
    importVertexColors: Optional[bool] = None
    indexFormat: Optional[int] = None
    legacyComputeAllNormalsFromSmoothingGroupsWhenMeshHasBlendShapes: Optional[bool] = None
    m_AddHumanoidExtraRootOnlyWhenUsingAvatar: Optional[bool] = None
    m_AutoGenerateAvatarMappingIfUnspecified: Optional[bool] = None
    m_AutoMapExternalMaterials: Optional[bool] = None
    m_AvatarSetup: Optional[int] = None
    m_ContainsAnimation: Optional[bool] = None
    m_CopyAvatar: Optional[bool] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_ExtraUserProperties: Optional[List[str]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_FileIdsGeneration: Optional[int] = None
    m_FileScaleFactor: Optional[float] = None
    m_FileScaleUnit: Optional[str] = None
    m_HasEmbeddedTextures: Optional[bool] = None
    m_HasPreviousCalculatedGlobalScale: Optional[bool] = None
    m_HumanoidOversampling: Optional[int] = None
    m_ImportAnimatedCustomProperties: Optional[bool] = None
    m_ImportBlendShapeDeformPercent: Optional[bool] = None
    m_ImportCameras: Optional[bool] = None
    m_ImportConstraints: Optional[bool] = None
    m_ImportLights: Optional[bool] = None
    m_ImportMaterials: Optional[bool] = None
    m_ImportPhysicalCameras: Optional[bool] = None
    m_ImportVisibility: Optional[bool] = None
    m_InternalIDToNameTable: Optional[List[Tuple[Tuple[int, int], str]]] = None
    m_MaterialImportMode: Optional[int] = None
    m_MaterialLocation: Optional[int] = None
    m_Materials: Optional[List[SourceAssetIdentifier]] = None
    m_NodeNameCollisionStrategy: Optional[int] = None
    m_PreBakeConvexCollisionMesh: Optional[bool] = None
    m_PreBakeTriangleCollisionMesh: Optional[bool] = None
    m_PreserveHierarchy: Optional[bool] = None
    m_PreviousCalculatedGlobalScale: Optional[float] = None
    m_RemapMaterialsIfMaterialImportModeIsNone: Optional[bool] = None
    m_RemoveConstantScaleCurves: Optional[bool] = None
    m_ResampleCurves: Optional[bool] = None
    m_ResampleRotations: Optional[bool] = None
    m_RigImportErrors: Optional[str] = None
    m_RigImportWarnings: Optional[str] = None
    m_SearchTexturesGlobally: Optional[bool] = None
    m_SortHierarchyByName: Optional[bool] = None
    m_StrictVertexDataChecks: Optional[bool] = None
    m_SupportsEmbeddedMaterials: Optional[bool] = None
    m_UseSRGBMaterialColor: Optional[bool] = None
    m_UsedFileIDs: Optional[List[int]] = None
    maxBonesPerVertex: Optional[int] = None
    maximumMeshLod: Optional[int] = None
    meshLodGenerationFlags: Optional[int] = None
    meshOptimizationFlags: Optional[int] = None
    minBoneWeight: Optional[float] = None
    normalCalculationMode: Optional[int] = None
    normalSmoothingSource: Optional[int] = None
    optimizeBones: Optional[bool] = None
    optimizeMeshForGPU: Optional[bool] = None
    secondaryUVMarginMethod: Optional[int] = None
    secondaryUVMinLightmapResolution: Optional[float] = None
    secondaryUVMinObjectScale: Optional[float] = None
    skinWeightsMode: Optional[int] = None
    splitTangentsAcrossUV: Optional[bool] = None


@unitypy_define
class MonoImporter(AssetImporter):
    executionOrder: int
    icon: PPtr[Texture2D]
    m_DefaultReferences: List[Tuple[str, PPtr[Object]]]
    m_Name: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class MovieImporter(AssetImporter):
    m_Name: str
    m_Quality: float
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_LinearTexture: Optional[bool] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class MultiArtifactTestImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class NativeFormatImporter(AssetImporter):
    m_Name: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_MainObjectFileID: Optional[int] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class PVRImporter(AssetImporter):
    m_Name: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UserData: Optional[str] = None


@unitypy_define
class PackageManifestImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class PluginImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExecutionOrder: List[Tuple[str, int]]
    m_IconMap: List[Tuple[str, PPtr[Texture2D]]]
    m_IsPreloaded: bool
    m_Name: str
    m_Output: PluginImportOutput
    m_PlatformData: Union[List[Tuple[Tuple[str, str], PlatformSettingsData]], List[Tuple[str, PlatformSettingsData]]]
    m_UserData: str
    m_DefineConstraints: Optional[List[str]] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_IsExplicitlyReferenced: Optional[bool] = None
    m_IsOverridable: Optional[bool] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_ValidateReferences: Optional[bool] = None


@unitypy_define
class PrefabImporter(AssetImporter):
    m_AddedObjectFileIDs: List[int]
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_IsPrefabVariant: bool
    m_Name: str
    m_UserData: str
    m_UnableToImportOnPreviousDomainReload: Optional[bool] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_VariantParentGUID: Optional[GUID] = None


@unitypy_define
class PreviewImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class RayTracingShaderImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str
    m_CurrentAPIMask: Optional[int] = None


@unitypy_define
class ReferencesArtifactGenerator(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class RoslynAdditionalFileImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class RoslynAnalyzerConfigImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class RuleSetFileImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class ScriptedImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_Name: str
    m_Script: PPtr[MonoScript]
    m_UserData: str
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_InternalIDToNameTable: Optional[List[Tuple[Tuple[int, int], str]]] = None
    m_UsedFileIDs: Optional[List[int]] = None


@unitypy_define
class ShaderImporter(AssetImporter):
    m_Name: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_DefaultTextures: Optional[List[Tuple[str, PPtr[Texture]]]] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_NonModifiableTextures: Optional[List[Tuple[str, PPtr[Texture]]]] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_PreprocessorOverride: Optional[int] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class ShaderIncludeImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str


@unitypy_define
class SpeedTreeImporter(AssetImporter):
    m_AlphaTestRef: float
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_BestWindQuality: int
    m_BillboardTransitionCrossFadeWidth: float
    m_EnableSmoothLODTransition: bool
    m_FadeOutWidth: float
    m_HasBillboard: bool
    m_HueVariation: ColorRGBA
    m_LODSettings: List[PerLODSettings]
    m_MainColor: ColorRGBA
    m_Name: str
    m_ScaleFactor: float
    m_UserData: str
    m_AnimateCrossFading: Optional[bool] = None
    m_EnableBumpMapping: Optional[bool] = None
    m_EnableHueVariation: Optional[bool] = None
    m_EnableLightProbes: Optional[bool] = None
    m_EnableShadowCasting: Optional[bool] = None
    m_EnableShadowReceiving: Optional[bool] = None
    m_EnableSubsurfaceScattering: Optional[bool] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDType: Optional[int] = None
    m_GenerateColliders: Optional[bool] = None
    m_GenerateRigidbody: Optional[bool] = None
    m_MaterialLocation: Optional[int] = None
    m_MaterialVersion: Optional[int] = None
    m_Materials: Optional[List[SourceAssetIdentifier]] = None
    m_MotionVectorModeEnumValue: Optional[int] = None
    m_ReflectionProbeEnumValue: Optional[int] = None
    m_SelectedWindQuality: Optional[int] = None
    m_Shininess: Optional[float] = None
    m_SpecColor: Optional[ColorRGBA] = None
    m_SupportsEmbeddedMaterials: Optional[bool] = None
    m_UnitConversionEnumValue: Optional[int] = None
    m_UsedFileIDs: Optional[List[int]] = None


@unitypy_define
class SpriteAtlasImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UsedFileIDs: List[int]
    m_UserData: str
    m_BindAsDefault: Optional[bool] = None
    m_PackingSettings: Optional[PackingSettings] = None
    m_PlatformSettings: Optional[List[TextureImporterPlatformSettings]] = None
    m_SecondaryTextureSettings: Optional[List[Tuple[str, SecondaryTextureSettings]]] = None
    m_TextureSettings: Optional[TextureSettings] = None
    m_VariantMultiplier: Optional[float] = None


@unitypy_define
class StyleSheetImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_Name: str
    m_UserData: str


@unitypy_define
class SubstanceImporter(AssetImporter):
    m_Name: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_DeletedPrototypes: Optional[List[str]] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_IsFirstImport: Optional[int] = None
    m_MaterialImportOutputs: Optional[List[MaterialImportOutput]] = None
    m_MaterialInstances: Optional[List[MaterialInstanceSettings]] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class TextScriptImporter(AssetImporter):
    m_Name: str
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class TextureImporter(AssetImporter):
    m_BorderMipMap: int
    m_ConvertToNormalMap: int
    m_EnableMipMap: int
    m_ExternalNormalMap: int
    m_FadeOut: int
    m_GenerateCubemap: int
    m_GrayScaleToAlpha: int
    m_HeightScale: float
    m_IsReadable: int
    m_Lightmap: int
    m_MaxTextureSize: int
    m_MipMapFadeDistanceEnd: int
    m_MipMapFadeDistanceStart: int
    m_MipMapMode: int
    m_NPOTScale: int
    m_Name: str
    m_NormalMapFilter: int
    m_TextureFormat: int
    m_TextureSettings: GLTextureSettings
    m_TextureType: int
    correctGamma: Optional[int] = None
    m_Alignment: Optional[int] = None
    m_AllowsAlphaSplitting: Optional[int] = None
    m_AlphaIsTransparency: Optional[int] = None
    m_AlphaTestReferenceValue: Optional[float] = None
    m_AlphaUsage: Optional[int] = None
    m_ApplyGammaDecoding: Optional[int] = None
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_BuildTargetSettings: Optional[List[BuildTargetSettings]] = None
    m_CompressionQuality: Optional[int] = None
    m_CompressionQualitySet: Optional[int] = None
    m_CookieLightType: Optional[int] = None
    m_CorrectGamma: Optional[int] = None
    m_CubemapConvolution: Optional[int] = None
    m_CubemapConvolutionExponent: Optional[float] = None
    m_CubemapConvolutionSteps: Optional[int] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_FlipGreenChannel: Optional[int] = None
    m_FlipbookColumns: Optional[int] = None
    m_FlipbookRows: Optional[int] = None
    m_IgnoreMasterTextureLimit: Optional[int] = None
    m_IgnoreMipmapLimit: Optional[int] = None
    m_IgnorePngGamma: Optional[Union[bool, int]] = None
    m_InternalIDToNameTable: Optional[List[Tuple[Tuple[int, int], str]]] = None
    m_LinearTexture: Optional[int] = None
    m_MaxTextureSizeSet: Optional[int] = None
    m_MipMapsPreserveCoverage: Optional[int] = None
    m_MipmapLimitGroupName: Optional[str] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_Output: Optional[TextureImportOutput] = None
    m_PSDRemoveMatte: Optional[bool] = None
    m_PSDShowRemoveMatteOption: Optional[bool] = None
    m_PlatformSettings: Optional[Union[List[PlatformSettings], List[TextureImporterPlatformSettings]]] = None
    m_PushPullDilation: Optional[int] = None
    m_RGBM: Optional[int] = None
    m_RecommendedTextureFormat: Optional[int] = None
    m_SeamlessCubemap: Optional[int] = None
    m_SingleChannelComponent: Optional[int] = None
    m_SourceTextureInformation: Optional[SourceTextureInformation] = None
    m_SpriteBorder: Optional[Vector4f] = None
    m_SpriteExtrude: Optional[int] = None
    m_SpriteGenerateFallbackPhysicsShape: Optional[int] = None
    m_SpriteGeometrySubdivision: Optional[float] = None
    m_SpriteMeshType: Optional[int] = None
    m_SpriteMode: Optional[int] = None
    m_SpritePackingTag: Optional[str] = None
    m_SpritePivot: Optional[Vector2f] = None
    m_SpritePixelsToUnits: Optional[float] = None
    m_SpriteSheet: Optional[SpriteSheetMetaData] = None
    m_SpriteTessellationDetail: Optional[float] = None
    m_SpriteTessellationMethod: Optional[int] = None
    m_StreamingMipmaps: Optional[int] = None
    m_StreamingMipmapsPriority: Optional[int] = None
    m_Swizzle: Optional[int] = None
    m_TextureFormatSet: Optional[int] = None
    m_TextureShape: Optional[int] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None
    m_VTOnly: Optional[int] = None
    m_sRGBTexture: Optional[int] = None


