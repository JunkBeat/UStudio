# type: ignore
from __future__ import annotations

from ._common import ABC, Object, unitypy_define


@unitypy_define
class AnnotationManager(Object):
    m_CurrentPreset_m_AnnotationList: List[Annotation]
    m_RecentlyChanged: List[Annotation]
    m_FadeGizmoSize: Optional[float] = None
    m_FadeGizmos: Optional[bool] = None
    m_IconSize: Optional[float] = None
    m_ShowGrid: Optional[bool] = None
    m_ShowLODLabels: Optional[bool] = None
    m_ShowSelectionOutline: Optional[bool] = None
    m_ShowSelectionWire: Optional[bool] = None
    m_Use3dGizmos: Optional[bool] = None
    m_WorldIconSize: Optional[float] = None


@unitypy_define
class AssetDatabaseV1(Object):
    m_AssetBundleNames: List[Tuple[int, AssetBundleFullName]]
    m_AssetTimeStamps: List[Tuple[str, AssetTimeStamp]]
    m_Assets: List[Tuple[GUID, Asset]]
    m_Metrics: AssetDatabaseMetrics
    m_UnityShadersVersion: int
    m_lastValidVersionHashes: Optional[List[Tuple[int, int]]] = None
    m_lastValidVersions: Optional[List[Tuple[AssetImporterHashKey, int]]] = None


@unitypy_define
class AssetMetaData(Object):
    assetStoreRef: int
    guid: GUID
    labels: List[str]
    originalName: str
    pathName: str
    licenseType: Optional[int] = None
    originalChangeset: Optional[int] = None
    originalDigest: Optional[Union[Hash128, MdFour]] = None
    originalParent: Optional[GUID] = None
    timeCreated: Optional[int] = None


@unitypy_define
class AssetServerCache(Object):
    m_CachesInitialized: int
    m_CommitItemSelection: List[GUID]
    m_DeletedItems: List[Tuple[GUID, DeletedItem]]
    m_Items: List[Tuple[GUID, Item]]
    m_LastCommitMessage: str
    m_LatestServerChangeset: int
    m_ModifiedItems: List[Tuple[GUID, Item]]
    m_WorkingItemMetaData: List[Tuple[GUID, CachedAssetMetaData]]


@unitypy_define
class AudioBuildInfo(Object):
    m_AudioClipCount: int
    m_AudioMixerCount: int
    m_IsAudioDisabled: bool


@unitypy_define
class BlockShaderSourceArtifact(Object):
    shaderName: str
    shaderSource: str


@unitypy_define
class BuiltAssetBundleInfoSet(Object):
    bundleInfos: List[BuiltAssetBundleInfo]


@unitypy_define
class ContentSummary(Object):
    m_assetStatsList: List[AssetStats]
    m_headerSize: int
    m_objectCount: int
    m_resourceDataSize: int
    m_resourceFileCount: int
    m_serializedFileCount: int
    m_serializedFileSize: int
    m_typeStatsList: List[TypeStats]
    m_generatedFileCount: Optional[int] = None
    m_generatedFileSize: Optional[int] = None
    m_reusedSerializedFileCount: Optional[int] = None
    m_reusedSerializedFileSize: Optional[int] = None
    m_sizeReusedContentInOutputDirectory: Optional[int] = None


@unitypy_define
class Derived(Object):
    pass


@unitypy_define
class SubDerived(Derived):
    pass


@unitypy_define
class DifferentMarshallingTestObject(Object):
    pass


@unitypy_define
class EditorBuildSettings(Object):
    m_Scenes: List[Scene]
    m_UseUCBPForAssetBundles: Optional[bool] = None
    m_configObjects: Optional[List[Tuple[str, PPtr[Object]]]] = None


@unitypy_define
class EditorExtension(Object, ABC):
    pass


@unitypy_define
class Component(EditorExtension):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class Behaviour(Component):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class Animation(Behaviour):
    m_AnimatePhysics: bool
    m_Animation: PPtr[AnimationClip]
    m_Animations: List[PPtr[AnimationClip]]
    m_CullingType: int
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_PlayAutomatically: bool
    m_WrapMode: int
    m_UpdateMode: Optional[int] = None
    m_UserAABB: Optional[AABB] = None


@unitypy_define
class Animator(Behaviour):
    m_ApplyRootMotion: bool
    m_Avatar: PPtr[Avatar]
    m_Controller: Union[PPtr[AnimatorController], PPtr[RuntimeAnimatorController]]
    m_CullingMode: int
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_AllowConstantClipSamplingOptimization: Optional[bool] = None
    m_AnimatePhysics: Optional[bool] = None
    m_HasTransformHierarchy: Optional[bool] = None
    m_KeepAnimatorControllerStateOnDisable: Optional[bool] = None
    m_KeepAnimatorStateOnDisable: Optional[bool] = None
    m_LinearVelocityBlending: Optional[bool] = None
    m_StabilizeFeet: Optional[bool] = None
    m_UpdateMode: Optional[int] = None
    m_WriteDefaultValuesOnDisable: Optional[bool] = None


@unitypy_define
class ArticulationBody(Behaviour):
    m_AnchorPosition: Vector3f
    m_AnchorRotation: Quaternionf
    m_AngularDamping: float
    m_ArticulationJointType: int
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Immovable: bool
    m_JointFriction: float
    m_LinearDamping: float
    m_LinearX: int
    m_LinearY: int
    m_LinearZ: int
    m_Mass: float
    m_ParentAnchorPosition: Vector3f
    m_ParentAnchorRotation: Quaternionf
    m_SwingY: int
    m_SwingZ: int
    m_Twist: int
    m_XDrive: ArticulationDrive
    m_YDrive: ArticulationDrive
    m_ZDrive: ArticulationDrive
    m_CenterOfMass: Optional[Vector3f] = None
    m_CollisionDetectionMode: Optional[int] = None
    m_ComputeParentAnchor: Optional[bool] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ImplicitCom: Optional[bool] = None
    m_ImplicitTensor: Optional[bool] = None
    m_IncludeLayers: Optional[BitField] = None
    m_InertiaRotation: Optional[Quaternionf] = None
    m_InertiaTensor: Optional[Vector3f] = None
    m_MatchAnchors: Optional[bool] = None
    m_UseGravity: Optional[bool] = None


@unitypy_define
class AudioBehaviour(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class AudioListener(AudioBehaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_ExtensionPropertyValues: Optional[List[ExtensionPropertyValue]] = None


@unitypy_define
class AudioSource(AudioBehaviour):
    BypassEffects: bool
    DopplerLevel: float
    Loop: bool
    MaxDistance: float
    MinDistance: float
    Mute: bool
    Pan2D: float
    Priority: int
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Pitch: float
    m_PlayOnAwake: bool
    m_Volume: float
    m_audioClip: PPtr[AudioClip]
    panLevelCustomCurve: AnimationCurve
    rolloffCustomCurve: AnimationCurve
    rolloffMode: int
    spreadCustomCurve: AnimationCurve
    BypassListenerEffects: Optional[bool] = None
    BypassReverbZones: Optional[bool] = None
    OutputAudioMixerGroup: Optional[PPtr[AudioMixerGroup]] = None
    Spatialize: Optional[bool] = None
    SpatializePostEffects: Optional[bool] = None
    m_ExtensionPropertyValues: Optional[List[ExtensionPropertyValue]] = None
    m_Resource: Optional[Union[PPtr[AudioResource], PPtr[Object]]] = None
    reverbZoneMixCustomCurve: Optional[AnimationCurve] = None


@unitypy_define
class AudioFilter(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class AudioChorusFilter(AudioFilter):
    m_Delay: float
    m_Depth: float
    m_DryMix: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Rate: float
    m_WetMix1: float
    m_WetMix2: float
    m_WetMix3: float
    m_FeedBack: Optional[float] = None


@unitypy_define
class AudioDistortionFilter(AudioFilter):
    m_DistortionLevel: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]


@unitypy_define
class AudioEchoFilter(AudioFilter):
    m_DecayRatio: float
    m_Delay: Union[float, int]
    m_DryMix: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_WetMix: float


@unitypy_define
class AudioHighPassFilter(AudioFilter):
    m_CutoffFrequency: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_HighpassResonanceQ: float


@unitypy_define
class AudioLowPassFilter(AudioFilter):
    lowpassLevelCustomCurve: AnimationCurve
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_LowpassResonanceQ: float
    m_CutoffFrequency: Optional[float] = None


@unitypy_define
class AudioReverbFilter(AudioFilter):
    m_DecayHFRatio: float
    m_DecayTime: float
    m_Density: float
    m_Diffusion: float
    m_DryLevel: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_HFReference: float
    m_LFReference: float
    m_ReflectionsDelay: float
    m_ReflectionsLevel: float
    m_ReverbDelay: float
    m_ReverbLevel: float
    m_ReverbPreset: int
    m_Room: float
    m_RoomHF: float
    m_RoomLF: float
    m_RoomRolloff: Optional[float] = None


@unitypy_define
class AudioReverbZone(Behaviour):
    m_DecayHFRatio: float
    m_DecayTime: float
    m_Density: float
    m_Diffusion: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_HFReference: float
    m_LFReference: float
    m_MaxDistance: float
    m_MinDistance: float
    m_Reflections: int
    m_ReflectionsDelay: float
    m_Reverb: int
    m_ReverbDelay: float
    m_ReverbPreset: int
    m_Room: int
    m_RoomHF: int
    m_RoomLF: int
    m_RoomRolloffFactor: Optional[float] = None


@unitypy_define
class Camera(Behaviour):
    far_clip_plane: float
    field_of_view: float
    m_BackGroundColor: ColorRGBA
    m_ClearFlags: int
    m_CullingMask: BitField
    m_Depth: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_NormalizedViewPortRect: Rectf
    m_RenderingPath: int
    m_TargetTexture: PPtr[RenderTexture]
    near_clip_plane: float
    orthographic: bool
    orthographic_size: float
    m_AllowDynamicResolution: Optional[bool] = None
    m_AllowMSAA: Optional[bool] = None
    m_Anamorphism: Optional[float] = None
    m_Aperture: Optional[float] = None
    m_BarrelClipping: Optional[float] = None
    m_BladeCount: Optional[int] = None
    m_Curvature: Optional[Vector2f] = None
    m_FocalLength: Optional[float] = None
    m_FocusDistance: Optional[float] = None
    m_ForceIntoRT: Optional[bool] = None
    m_GateFitMode: Optional[int] = None
    m_HDR: Optional[bool] = None
    m_Iso: Optional[int] = None
    m_LensShift: Optional[Vector2f] = None
    m_OcclusionCulling: Optional[bool] = None
    m_SensorSize: Optional[Vector2f] = None
    m_ShutterSpeed: Optional[float] = None
    m_StereoConvergence: Optional[float] = None
    m_StereoMirrorMode: Optional[bool] = None
    m_StereoSeparation: Optional[float] = None
    m_TargetDisplay: Optional[int] = None
    m_TargetEye: Optional[int] = None
    m_projectionMatrixMode: Optional[int] = None


@unitypy_define
class ScriptableCamera(Camera):
    far_clip_plane: float
    field_of_view: float
    m_AllowDynamicResolution: bool
    m_AllowMSAA: bool
    m_BackGroundColor: ColorRGBA
    m_ClearFlags: int
    m_CullingMask: BitField
    m_Depth: float
    m_Enabled: int
    m_FocalLength: float
    m_ForceIntoRT: bool
    m_GameObject: PPtr[GameObject]
    m_GateFitMode: int
    m_HDR: bool
    m_LensShift: Vector2f
    m_NormalizedViewPortRect: Rectf
    m_OcclusionCulling: bool
    m_RenderingPath: int
    m_Script: PPtr[MonoScript]
    m_SensorSize: Vector2f
    m_StereoConvergence: float
    m_StereoSeparation: float
    m_TargetDisplay: int
    m_TargetEye: int
    m_TargetTexture: PPtr[RenderTexture]
    m_projectionMatrixMode: int
    near_clip_plane: float
    orthographic: bool
    orthographic_size: float


@unitypy_define
class Canvas(Behaviour):
    m_Camera: PPtr[Camera]
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_PixelPerfect: bool
    m_RenderMode: int
    m_AdditionalShaderChannelsFlag: Optional[int] = None
    m_Alpha: Optional[float] = None
    m_Normals: Optional[bool] = None
    m_OverridePixelPerfect: Optional[bool] = None
    m_OverrideSorting: Optional[bool] = None
    m_PlaneDistance: Optional[float] = None
    m_PositionUVs: Optional[bool] = None
    m_ReceivesEvents: Optional[bool] = None
    m_SortingBucketNormalizedSize: Optional[float] = None
    m_SortingLayerID: Optional[int] = None
    m_SortingOrder: Optional[int] = None
    m_TargetDisplay: Optional[int] = None
    m_UpdateRectTransformForStandalone: Optional[int] = None
    m_UseReflectionProbes: Optional[bool] = None
    m_VertexColorAlwaysGammaSpace: Optional[bool] = None


@unitypy_define
class CanvasGroup(Behaviour):
    m_Alpha: float
    m_BlocksRaycasts: bool
    m_GameObject: PPtr[GameObject]
    m_IgnoreParentGroups: bool
    m_Interactable: bool
    m_Enabled: Optional[int] = None


@unitypy_define
class Cloth(Behaviour):
    m_GameObject: PPtr[GameObject]
    m_BendingStiffness: Optional[float] = None
    m_CapsuleColliders: Optional[List[PPtr[CapsuleCollider]]] = None
    m_Coefficients: Optional[List[ClothConstrainCoefficients]] = None
    m_CollisionMassScale: Optional[float] = None
    m_Damping: Optional[float] = None
    m_Enabled: Optional[int] = None
    m_ExternalAcceleration: Optional[Vector3f] = None
    m_Friction: Optional[float] = None
    m_RandomAcceleration: Optional[Vector3f] = None
    m_SelfAndInterCollisionIndices: Optional[List[int]] = None
    m_SelfCollisionDistance: Optional[float] = None
    m_SelfCollisionStiffness: Optional[float] = None
    m_SleepThreshold: Optional[float] = None
    m_SolverFrequency: Optional[Union[float, int]] = None
    m_SphereColliders: Optional[Union[List[ClothSphereColliderPair], List[Tuple[PPtr[SphereCollider], PPtr[SphereCollider]]]]] = None
    m_StretchingStiffness: Optional[float] = None
    m_UseContinuousCollision: Optional[bool] = None
    m_UseGravity: Optional[bool] = None
    m_UseTethers: Optional[bool] = None
    m_UseVirtualParticles: Optional[bool] = None
    m_VirtualParticleIndices: Optional[List[int]] = None
    m_VirtualParticleWeights: Optional[List[Vector3f]] = None
    m_WorldAccelerationScale: Optional[float] = None
    m_WorldVelocityScale: Optional[float] = None


@unitypy_define
class InteractiveCloth(Cloth):
    m_AttachedColliders: List[ClothAttachment]
    m_AttachmentResponse: float
    m_AttachmentTearFactor: float
    m_BendingStiffness: float
    m_CollisionResponse: float
    m_Damping: float
    m_Density: float
    m_Enabled: int
    m_ExternalAcceleration: Vector3f
    m_Friction: float
    m_GameObject: PPtr[GameObject]
    m_Mesh: PPtr[Mesh]
    m_Pressure: float
    m_RandomAcceleration: Vector3f
    m_SelfCollision: bool
    m_StretchingStiffness: float
    m_TearFactor: float
    m_Thickness: float
    m_UseGravity: bool


@unitypy_define
class SkinnedCloth(Cloth):
    m_BendingStiffness: float
    m_Coefficients: List[ClothConstrainCoefficients]
    m_Damping: float
    m_Enabled: int
    m_ExternalAcceleration: Vector3f
    m_GameObject: PPtr[GameObject]
    m_RandomAcceleration: Vector3f
    m_SelfCollision: bool
    m_StretchingStiffness: float
    m_Thickness: float
    m_UseGravity: bool
    m_WorldAccelerationScale: float
    m_WorldVelocityScale: float


@unitypy_define
class CloudServiceHandlerBehaviour(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]


@unitypy_define
class Collider2D(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class BoxCollider2D(Collider2D):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: PPtr[PhysicsMaterial2D]
    m_Size: Vector2f
    m_AutoTiling: Optional[bool] = None
    m_CallbackLayers: Optional[BitField] = None
    m_Center: Optional[Vector2f] = None
    m_CompositeOperation: Optional[int] = None
    m_CompositeOrder: Optional[int] = None
    m_ContactCaptureLayers: Optional[BitField] = None
    m_Density: Optional[float] = None
    m_EdgeRadius: Optional[float] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ForceReceiveLayers: Optional[BitField] = None
    m_ForceSendLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_Offset: Optional[Vector2f] = None
    m_SpriteTilingProperty: Optional[SpriteTilingProperty] = None
    m_UsedByComposite: Optional[bool] = None
    m_UsedByEffector: Optional[bool] = None


@unitypy_define
class CapsuleCollider2D(Collider2D):
    m_Density: float
    m_Direction: int
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: PPtr[PhysicsMaterial2D]
    m_Offset: Vector2f
    m_Size: Vector2f
    m_UsedByEffector: bool
    m_CallbackLayers: Optional[BitField] = None
    m_CompositeOperation: Optional[int] = None
    m_CompositeOrder: Optional[int] = None
    m_ContactCaptureLayers: Optional[BitField] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ForceReceiveLayers: Optional[BitField] = None
    m_ForceSendLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_UsedByComposite: Optional[bool] = None


@unitypy_define
class CircleCollider2D(Collider2D):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: PPtr[PhysicsMaterial2D]
    m_Radius: float
    m_CallbackLayers: Optional[BitField] = None
    m_Center: Optional[Vector2f] = None
    m_CompositeOperation: Optional[int] = None
    m_CompositeOrder: Optional[int] = None
    m_ContactCaptureLayers: Optional[BitField] = None
    m_Density: Optional[float] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ForceReceiveLayers: Optional[BitField] = None
    m_ForceSendLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_Offset: Optional[Vector2f] = None
    m_UsedByComposite: Optional[bool] = None
    m_UsedByEffector: Optional[bool] = None


@unitypy_define
class CompositeCollider2D(Collider2D):
    m_ColliderPaths: List[SubCollider]
    m_CompositePaths: Polygon2D
    m_Density: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_GenerationType: int
    m_GeometryType: int
    m_IsTrigger: bool
    m_Material: PPtr[PhysicsMaterial2D]
    m_Offset: Vector2f
    m_UsedByEffector: bool
    m_VertexDistance: float
    m_CallbackLayers: Optional[BitField] = None
    m_CompositeGameObject: Optional[PPtr[GameObject]] = None
    m_CompositeOperation: Optional[int] = None
    m_CompositeOrder: Optional[int] = None
    m_ContactCaptureLayers: Optional[BitField] = None
    m_EdgeRadius: Optional[float] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ForceReceiveLayers: Optional[BitField] = None
    m_ForceSendLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_OffsetDistance: Optional[float] = None
    m_UseDelaunayMesh: Optional[bool] = None
    m_UsedByComposite: Optional[bool] = None


@unitypy_define
class CustomCollider2D(Collider2D):
    m_CustomShapes: PhysicsShapeGroup2D
    m_Density: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: PPtr[PhysicsMaterial2D]
    m_Offset: Vector2f
    m_UsedByEffector: bool
    m_CallbackLayers: Optional[BitField] = None
    m_CompositeOperation: Optional[int] = None
    m_CompositeOrder: Optional[int] = None
    m_ContactCaptureLayers: Optional[BitField] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ForceReceiveLayers: Optional[BitField] = None
    m_ForceSendLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_UsedByComposite: Optional[bool] = None


@unitypy_define
class EdgeCollider2D(Collider2D):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: PPtr[PhysicsMaterial2D]
    m_Points: List[Vector2f]
    m_AdjacentEndPoint: Optional[Vector2f] = None
    m_AdjacentStartPoint: Optional[Vector2f] = None
    m_CallbackLayers: Optional[BitField] = None
    m_CompositeOperation: Optional[int] = None
    m_CompositeOrder: Optional[int] = None
    m_ContactCaptureLayers: Optional[BitField] = None
    m_Density: Optional[float] = None
    m_EdgeRadius: Optional[float] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ForceReceiveLayers: Optional[BitField] = None
    m_ForceSendLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_Offset: Optional[Vector2f] = None
    m_UseAdjacentEndPoint: Optional[bool] = None
    m_UseAdjacentStartPoint: Optional[bool] = None
    m_UsedByComposite: Optional[bool] = None
    m_UsedByEffector: Optional[bool] = None


@unitypy_define
class PolygonCollider2D(Collider2D):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: PPtr[PhysicsMaterial2D]
    m_AutoTiling: Optional[bool] = None
    m_CallbackLayers: Optional[BitField] = None
    m_CompositeOperation: Optional[int] = None
    m_CompositeOrder: Optional[int] = None
    m_ContactCaptureLayers: Optional[BitField] = None
    m_Density: Optional[float] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ForceReceiveLayers: Optional[BitField] = None
    m_ForceSendLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_Offset: Optional[Vector2f] = None
    m_Points: Optional[Polygon2D] = None
    m_Poly: Optional[Polygon2D] = None
    m_SpriteTilingProperty: Optional[SpriteTilingProperty] = None
    m_UseDelaunayMesh: Optional[bool] = None
    m_UsedByComposite: Optional[bool] = None
    m_UsedByEffector: Optional[bool] = None


@unitypy_define
class PolygonColliderBase2D(Collider2D):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class TilemapCollider2D(Collider2D):
    m_Density: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: PPtr[PhysicsMaterial2D]
    m_Offset: Vector2f
    m_UsedByEffector: bool
    m_CallbackLayers: Optional[BitField] = None
    m_CompositeOperation: Optional[int] = None
    m_CompositeOrder: Optional[int] = None
    m_ContactCaptureLayers: Optional[BitField] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ExtrusionFactor: Optional[float] = None
    m_ForceReceiveLayers: Optional[BitField] = None
    m_ForceSendLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_MaximumTileChangeCount: Optional[int] = None
    m_UseDelaunayMesh: Optional[bool] = None
    m_UsedByComposite: Optional[bool] = None


@unitypy_define
class ConstantForce(Behaviour):
    m_Enabled: int
    m_Force: Vector3f
    m_GameObject: PPtr[GameObject]
    m_RelativeForce: Vector3f
    m_RelativeTorque: Vector3f
    m_Torque: Vector3f


@unitypy_define
class Effector2D(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class AreaEffector2D(Effector2D):
    m_ColliderMask: BitField
    m_Enabled: int
    m_ForceMagnitude: float
    m_ForceTarget: int
    m_ForceVariation: float
    m_GameObject: PPtr[GameObject]
    m_AngularDamping: Optional[float] = None
    m_AngularDrag: Optional[float] = None
    m_Drag: Optional[float] = None
    m_ForceAngle: Optional[float] = None
    m_ForceDirection: Optional[float] = None
    m_LinearDamping: Optional[float] = None
    m_UseColliderMask: Optional[bool] = None
    m_UseGlobalAngle: Optional[bool] = None


@unitypy_define
class BuoyancyEffector2D(Effector2D):
    m_ColliderMask: BitField
    m_Density: float
    m_Enabled: int
    m_FlowAngle: float
    m_FlowMagnitude: float
    m_FlowVariation: float
    m_GameObject: PPtr[GameObject]
    m_SurfaceLevel: float
    m_UseColliderMask: bool
    m_AngularDamping: Optional[float] = None
    m_AngularDrag: Optional[float] = None
    m_LinearDamping: Optional[float] = None
    m_LinearDrag: Optional[float] = None


@unitypy_define
class PlatformEffector2D(Effector2D):
    m_ColliderMask: BitField
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_OneWay: Optional[bool] = None
    m_RotationalOffset: Optional[float] = None
    m_SideAngleVariance: Optional[float] = None
    m_SideArc: Optional[float] = None
    m_SideBounce: Optional[bool] = None
    m_SideFriction: Optional[bool] = None
    m_SurfaceArc: Optional[float] = None
    m_UseColliderMask: Optional[bool] = None
    m_UseOneWay: Optional[bool] = None
    m_UseOneWayGrouping: Optional[bool] = None
    m_UseSideBounce: Optional[bool] = None
    m_UseSideFriction: Optional[bool] = None


@unitypy_define
class PointEffector2D(Effector2D):
    m_ColliderMask: BitField
    m_DistanceScale: float
    m_Enabled: int
    m_ForceMagnitude: float
    m_ForceMode: int
    m_ForceSource: int
    m_ForceTarget: int
    m_ForceVariation: float
    m_GameObject: PPtr[GameObject]
    m_AngularDamping: Optional[float] = None
    m_AngularDrag: Optional[float] = None
    m_Drag: Optional[float] = None
    m_LinearDamping: Optional[float] = None
    m_UseColliderMask: Optional[bool] = None


@unitypy_define
class SurfaceEffector2D(Effector2D):
    m_ColliderMask: BitField
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Speed: float
    m_SpeedVariation: float
    m_ForceScale: Optional[float] = None
    m_UseBounce: Optional[bool] = None
    m_UseColliderMask: Optional[bool] = None
    m_UseContactForce: Optional[bool] = None
    m_UseFriction: Optional[bool] = None


@unitypy_define
class FlareLayer(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]


@unitypy_define
class GUIElement(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class GUIText(GUIElement):
    m_Alignment: int
    m_Anchor: int
    m_Enabled: int
    m_Font: PPtr[Font]
    m_FontSize: int
    m_FontStyle: int
    m_GameObject: PPtr[GameObject]
    m_LineSpacing: float
    m_Material: PPtr[Material]
    m_PixelCorrect: bool
    m_PixelOffset: Vector2f
    m_TabSize: float
    m_Text: str
    m_Color: Optional[ColorRGBA] = None
    m_RichText: Optional[bool] = None


@unitypy_define
class GUITexture(GUIElement):
    m_BottomBorder: int
    m_Color: ColorRGBA
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_LeftBorder: int
    m_PixelInset: Rectf
    m_RightBorder: int
    m_Texture: PPtr[Texture]
    m_TopBorder: int


@unitypy_define
class GUILayer(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]


@unitypy_define
class GridLayout(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class Grid(GridLayout):
    m_CellGap: Vector3f
    m_CellLayout: int
    m_CellSize: Vector3f
    m_CellSwizzle: int
    m_Enabled: int
    m_GameObject: PPtr[GameObject]


@unitypy_define
class Tilemap(GridLayout):
    m_AnimatedTiles: List[Tuple[int3_storage, TileAnimationData]]
    m_AnimationFrameRate: float
    m_Color: ColorRGBA
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Origin: int3_storage
    m_Size: int3_storage
    m_TileAnchor: Vector3f
    m_TileAssetArray: List[TilemapRefCountedData]
    m_TileColorArray: List[TilemapRefCountedData]
    m_TileMatrixArray: List[TilemapRefCountedData]
    m_TileOrientation: int
    m_TileOrientationMatrix: Matrix4x4f
    m_TileSpriteArray: List[TilemapRefCountedData]
    m_Tiles: List[Tuple[int3_storage, Tile]]
    m_TileObjectToInstantiateArray: Optional[List[TilemapRefCountedData]] = None


@unitypy_define
class Halo(Behaviour):
    m_Color: ColorRGBA
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Size: float


@unitypy_define
class HaloLayer(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]


@unitypy_define
class IConstraint(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class AimConstraint(IConstraint):
    m_AffectRotationX: bool
    m_AffectRotationY: bool
    m_AffectRotationZ: bool
    m_AimVector: Vector3f
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_RotationAtRest: Vector3f
    m_RotationOffset: Vector3f
    m_Sources: List[ConstraintSource]
    m_UpType: int
    m_UpVector: Vector3f
    m_Weight: float
    m_WorldUpObject: PPtr[Transform]
    m_WorldUpVector: Vector3f
    m_Active: Optional[bool] = None
    m_IsContraintActive: Optional[bool] = None


@unitypy_define
class LookAtConstraint(IConstraint):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Roll: float
    m_RotationAtRest: Vector3f
    m_RotationOffset: Vector3f
    m_Sources: List[ConstraintSource]
    m_UseUpObject: bool
    m_Weight: float
    m_WorldUpObject: PPtr[Transform]
    m_Active: Optional[bool] = None
    m_IsContraintActive: Optional[bool] = None


@unitypy_define
class ParentConstraint(IConstraint):
    m_AffectRotationX: bool
    m_AffectRotationY: bool
    m_AffectRotationZ: bool
    m_AffectTranslationX: bool
    m_AffectTranslationY: bool
    m_AffectTranslationZ: bool
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_RotationAtRest: Vector3f
    m_RotationOffsets: List[Vector3f]
    m_Sources: List[ConstraintSource]
    m_TranslationAtRest: Vector3f
    m_TranslationOffsets: List[Vector3f]
    m_Weight: float
    m_Active: Optional[bool] = None
    m_IsContraintActive: Optional[bool] = None


@unitypy_define
class PositionConstraint(IConstraint):
    m_AffectTranslationX: bool
    m_AffectTranslationY: bool
    m_AffectTranslationZ: bool
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Sources: List[ConstraintSource]
    m_TranslationAtRest: Vector3f
    m_TranslationOffset: Vector3f
    m_Weight: float
    m_Active: Optional[bool] = None
    m_IsContraintActive: Optional[bool] = None


@unitypy_define
class RotationConstraint(IConstraint):
    m_AffectRotationX: bool
    m_AffectRotationY: bool
    m_AffectRotationZ: bool
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_RotationAtRest: Vector3f
    m_RotationOffset: Vector3f
    m_Sources: List[ConstraintSource]
    m_Weight: float
    m_Active: Optional[bool] = None
    m_IsContraintActive: Optional[bool] = None


@unitypy_define
class ScaleConstraint(IConstraint):
    m_AffectScalingX: bool
    m_AffectScalingY: bool
    m_AffectScalingZ: bool
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_ScaleAtRest: Vector3f
    m_ScaleOffset: Vector3f
    m_Sources: List[ConstraintSource]
    m_Weight: float
    m_Active: Optional[bool] = None
    m_IsContraintActive: Optional[bool] = None


@unitypy_define
class Joint2D(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class AnchoredJoint2D(Joint2D):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class DistanceJoint2D(AnchoredJoint2D):
    m_Anchor: Vector2f
    m_ConnectedAnchor: Vector2f
    m_ConnectedRigidBody: PPtr[Rigidbody2D]
    m_Distance: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_AutoConfigureConnectedAnchor: Optional[bool] = None
    m_AutoConfigureDistance: Optional[bool] = None
    m_BreakAction: Optional[int] = None
    m_BreakForce: Optional[float] = None
    m_BreakTorque: Optional[float] = None
    m_CollideConnected: Optional[bool] = None
    m_EnableCollision: Optional[bool] = None
    m_MaxDistanceOnly: Optional[bool] = None


@unitypy_define
class FixedJoint2D(AnchoredJoint2D):
    m_Anchor: Vector2f
    m_AutoConfigureConnectedAnchor: bool
    m_BreakForce: float
    m_BreakTorque: float
    m_ConnectedAnchor: Vector2f
    m_ConnectedRigidBody: PPtr[Rigidbody2D]
    m_DampingRatio: float
    m_EnableCollision: bool
    m_Enabled: int
    m_Frequency: float
    m_GameObject: PPtr[GameObject]
    m_BreakAction: Optional[int] = None


@unitypy_define
class FrictionJoint2D(AnchoredJoint2D):
    m_Anchor: Vector2f
    m_AutoConfigureConnectedAnchor: bool
    m_BreakForce: float
    m_BreakTorque: float
    m_ConnectedAnchor: Vector2f
    m_ConnectedRigidBody: PPtr[Rigidbody2D]
    m_EnableCollision: bool
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_MaxForce: float
    m_MaxTorque: float
    m_BreakAction: Optional[int] = None


@unitypy_define
class HingeJoint2D(AnchoredJoint2D):
    m_Anchor: Vector2f
    m_AngleLimits: Union[JointAngleLimit2D, JointAngleLimits2D]
    m_ConnectedAnchor: Vector2f
    m_ConnectedRigidBody: PPtr[Rigidbody2D]
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Motor: JointMotor2D
    m_UseLimits: bool
    m_UseMotor: bool
    m_AutoConfigureConnectedAnchor: Optional[bool] = None
    m_BreakAction: Optional[int] = None
    m_BreakForce: Optional[float] = None
    m_BreakTorque: Optional[float] = None
    m_CollideConnected: Optional[bool] = None
    m_EnableCollision: Optional[bool] = None
    m_UseConnectedAnchor: Optional[bool] = None


@unitypy_define
class SliderJoint2D(AnchoredJoint2D):
    m_Anchor: Vector2f
    m_Angle: float
    m_ConnectedAnchor: Vector2f
    m_ConnectedRigidBody: PPtr[Rigidbody2D]
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Motor: JointMotor2D
    m_TranslationLimits: JointTranslationLimits2D
    m_UseLimits: bool
    m_UseMotor: bool
    m_AutoConfigureAngle: Optional[bool] = None
    m_AutoConfigureConnectedAnchor: Optional[bool] = None
    m_BreakAction: Optional[int] = None
    m_BreakForce: Optional[float] = None
    m_BreakTorque: Optional[float] = None
    m_CollideConnected: Optional[bool] = None
    m_EnableCollision: Optional[bool] = None


@unitypy_define
class SpringJoint2D(AnchoredJoint2D):
    m_Anchor: Vector2f
    m_ConnectedAnchor: Vector2f
    m_ConnectedRigidBody: PPtr[Rigidbody2D]
    m_DampingRatio: float
    m_Distance: float
    m_Enabled: int
    m_Frequency: float
    m_GameObject: PPtr[GameObject]
    m_AutoConfigureConnectedAnchor: Optional[bool] = None
    m_AutoConfigureDistance: Optional[bool] = None
    m_BreakAction: Optional[int] = None
    m_BreakForce: Optional[float] = None
    m_BreakTorque: Optional[float] = None
    m_CollideConnected: Optional[bool] = None
    m_EnableCollision: Optional[bool] = None


@unitypy_define
class WheelJoint2D(AnchoredJoint2D):
    m_Anchor: Vector2f
    m_ConnectedAnchor: Vector2f
    m_ConnectedRigidBody: PPtr[Rigidbody2D]
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Motor: JointMotor2D
    m_Suspension: JointSuspension2D
    m_UseMotor: bool
    m_AutoConfigureConnectedAnchor: Optional[bool] = None
    m_BreakAction: Optional[int] = None
    m_BreakForce: Optional[float] = None
    m_BreakTorque: Optional[float] = None
    m_CollideConnected: Optional[bool] = None
    m_EnableCollision: Optional[bool] = None


@unitypy_define
class RelativeJoint2D(Joint2D):
    m_AngularOffset: float
    m_AutoConfigureOffset: bool
    m_BreakForce: float
    m_BreakTorque: float
    m_ConnectedRigidBody: PPtr[Rigidbody2D]
    m_CorrectionScale: float
    m_EnableCollision: bool
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_LinearOffset: Vector2f
    m_MaxForce: float
    m_MaxTorque: float
    m_BreakAction: Optional[int] = None


@unitypy_define
class TargetJoint2D(Joint2D):
    m_Anchor: Vector2f
    m_AutoConfigureTarget: bool
    m_BreakForce: float
    m_BreakTorque: float
    m_ConnectedRigidBody: PPtr[Rigidbody2D]
    m_DampingRatio: float
    m_EnableCollision: bool
    m_Enabled: int
    m_Frequency: float
    m_GameObject: PPtr[GameObject]
    m_MaxForce: float
    m_Target: Vector2f
    m_BreakAction: Optional[int] = None


@unitypy_define
class LensFlare(Behaviour):
    m_Brightness: float
    m_Color: ColorRGBA
    m_Directional: bool
    m_Enabled: int
    m_Flare: PPtr[Flare]
    m_GameObject: PPtr[GameObject]
    m_IgnoreLayers: BitField
    m_FadeSpeed: Optional[float] = None


@unitypy_define
class Light(Behaviour):
    m_Color: ColorRGBA
    m_Cookie: PPtr[Texture]
    m_CullingMask: BitField
    m_DrawHalo: bool
    m_Enabled: int
    m_Flare: PPtr[Flare]
    m_GameObject: PPtr[GameObject]
    m_Intensity: float
    m_Lightmapping: int
    m_Range: float
    m_RenderMode: int
    m_Shadows: ShadowSettings
    m_SpotAngle: float
    m_Type: int
    m_ActuallyLightmapped: Optional[bool] = None
    m_AreaSize: Optional[Vector2f] = None
    m_BakedIndex: Optional[int] = None
    m_BakingOutput: Optional[LightBakingOutput] = None
    m_BounceIntensity: Optional[float] = None
    m_BoundingSphereOverride: Optional[Vector4f] = None
    m_CCT: Optional[float] = None
    m_ColorTemperature: Optional[float] = None
    m_CookieSize: Optional[float] = None
    m_CookieSize2D: Optional[Vector2f] = None
    m_EnableSpotReflector: Optional[bool] = None
    m_FalloffTable: Optional[FalloffTable] = None
    m_ForceVisible: Optional[bool] = None
    m_InnerSpotAngle: Optional[float] = None
    m_LightShadowCasterMode: Optional[int] = None
    m_LightUnit: Optional[int] = None
    m_LuxAtDistance: Optional[float] = None
    m_RenderingLayerMask: Optional[int] = None
    m_Shape: Optional[int] = None
    m_ShapeRadius: Optional[float] = None
    m_UseBoundingSphereOverride: Optional[bool] = None
    m_UseColorTemperature: Optional[bool] = None
    m_UseViewFrustumForShadowCasterCull: Optional[bool] = None


@unitypy_define
class LightProbeGroup(Behaviour):
    m_GameObject: PPtr[GameObject]
    m_Enabled: Optional[int] = None


@unitypy_define
class LightProbeProxyVolume(Behaviour):
    m_BoundingBoxMode: int
    m_BoundingBoxOrigin: Vector3f
    m_BoundingBoxSize: Vector3f
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_ProbePositionMode: int
    m_RefreshMode: int
    m_ResolutionMode: int
    m_ResolutionProbesPerUnit: float
    m_ResolutionX: int
    m_ResolutionY: int
    m_ResolutionZ: int
    m_DataFormat: Optional[int] = None
    m_QualityMode: Optional[int] = None


@unitypy_define
class MonoBehaviour(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Name: str
    m_Script: PPtr[MonoScript]


@unitypy_define
class NavMeshAgent(Behaviour):
    m_Acceleration: float
    m_AngularSpeed: float
    m_AutoRepath: bool
    m_AutoTraverseOffMeshLink: bool
    m_BaseOffset: float
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Height: float
    m_ObstacleAvoidanceType: int
    m_Radius: float
    m_Speed: float
    m_StoppingDistance: float
    m_WalkableMask: int
    avoidancePriority: Optional[int] = None
    m_AgentTypeID: Optional[int] = None
    m_AutoBraking: Optional[bool] = None


@unitypy_define
class NavMeshObstacle(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Carve: Optional[bool] = None
    m_CarveOnlyStationary: Optional[bool] = None
    m_Center: Optional[Vector3f] = None
    m_Extents: Optional[Vector3f] = None
    m_Height: Optional[float] = None
    m_MoveThreshold: Optional[float] = None
    m_Radius: Optional[float] = None
    m_Shape: Optional[int] = None
    m_TimeToStationary: Optional[float] = None


@unitypy_define
class NetworkView(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Observed: PPtr[Component]
    m_StateSynchronization: int
    m_ViewID: NetworkViewID


@unitypy_define
class OffMeshLink(Behaviour):
    m_Activated: bool
    m_BiDirectional: bool
    m_CostOverride: float
    m_End: PPtr[Transform]
    m_GameObject: PPtr[GameObject]
    m_Start: PPtr[Transform]
    m_AgentTypeID: Optional[int] = None
    m_AreaIndex: Optional[int] = None
    m_AutoUpdatePositions: Optional[bool] = None
    m_DtPolyRef: Optional[int] = None
    m_Enabled: Optional[int] = None
    m_NavMeshLayer: Optional[int] = None


@unitypy_define
class ParticleSystemForceField(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Parameters: ParticleSystemForceFieldParameters


