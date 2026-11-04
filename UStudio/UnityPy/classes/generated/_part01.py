# type: ignore
from __future__ import annotations

from ._common import unitypy_define
from ._part00 import Behaviour, Component


@unitypy_define
class PhysicsUpdateBehaviour2D(Behaviour):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class ConstantForce2D(PhysicsUpdateBehaviour2D):
    m_Enabled: int
    m_Force: Vector2f
    m_GameObject: PPtr[GameObject]
    m_RelativeForce: Vector2f
    m_Torque: float


@unitypy_define
class PlayableDirector(Behaviour):
    m_DirectorUpdateMode: int
    m_Enabled: int
    m_ExposedReferences: ExposedReferenceTable
    m_GameObject: PPtr[GameObject]
    m_InitialState: int
    m_InitialTime: float
    m_PlayableAsset: PPtr[Object]
    m_SceneBindings: List[DirectorGenericBinding]
    m_WrapMode: int


@unitypy_define
class Projector(Behaviour):
    m_AspectRatio: float
    m_Enabled: int
    m_FarClipPlane: float
    m_FieldOfView: float
    m_GameObject: PPtr[GameObject]
    m_IgnoreLayers: BitField
    m_Material: PPtr[Material]
    m_NearClipPlane: float
    m_Orthographic: bool
    m_OrthographicSize: float


@unitypy_define
class ReflectionProbe(Behaviour):
    m_BackGroundColor: ColorRGBA
    m_BakedTexture: PPtr[Texture]
    m_BoxOffset: Vector3f
    m_BoxProjection: bool
    m_BoxSize: Vector3f
    m_ClearFlags: int
    m_CullingMask: BitField
    m_CustomBakedTexture: PPtr[Texture]
    m_Enabled: int
    m_FarClip: float
    m_GameObject: PPtr[GameObject]
    m_HDR: bool
    m_Importance: int
    m_IntensityMultiplier: float
    m_Mode: int
    m_NearClip: float
    m_RefreshMode: int
    m_RenderDynamicObjects: bool
    m_Resolution: int
    m_ShadowDistance: float
    m_TimeSlicingMode: int
    m_Type: int
    m_UpdateFrequency: int
    m_UseOcclusionCulling: bool
    m_BlendDistance: Optional[float] = None


@unitypy_define
class Skybox(Behaviour):
    m_CustomSkybox: PPtr[Material]
    m_Enabled: int
    m_GameObject: PPtr[GameObject]


@unitypy_define
class SortingGroup(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_SortingLayer: int
    m_SortingOrder: int
    m_Sort3DAs2D: Optional[bool] = None
    m_SortAtRoot: Optional[bool] = None
    m_SortingLayerID: Optional[int] = None


@unitypy_define
class StreamingController(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_StreamingMipmapBias: float


@unitypy_define
class Terrain(Behaviour):
    m_BakeLightProbesForTrees: bool
    m_ChunkDynamicUVST: Vector4f
    m_DetailObjectDensity: float
    m_DetailObjectDistance: float
    m_DrawHeightmap: bool
    m_DrawTreesAndFoliage: bool
    m_DynamicUVST: Vector4f
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_HeightmapMaximumLOD: int
    m_HeightmapPixelError: float
    m_LightmapIndex: int
    m_LightmapIndexDynamic: int
    m_LightmapTilingOffset: Vector4f
    m_LightmapTilingOffsetDynamic: Vector4f
    m_MaterialTemplate: PPtr[Material]
    m_ReflectionProbeUsage: int
    m_SplatMapDistance: float
    m_TerrainData: PPtr[TerrainData]
    m_TreeBillboardDistance: float
    m_TreeCrossFadeLength: float
    m_TreeDistance: float
    m_TreeMaximumFullLODCount: int
    m_AllowAutoConnect: Optional[bool] = None
    m_CastShadows: Optional[bool] = None
    m_DefaultSmoothness: Optional[float] = None
    m_DrawInstanced: Optional[bool] = None
    m_EnableHeightmapLODFrustumCulling: Optional[bool] = None
    m_EnableHeightmapRayTracing: Optional[bool] = None
    m_EnableTreesAndDetailsRayTracing: Optional[bool] = None
    m_ExplicitProbeSetHash: Optional[Hash128] = None
    m_GroupingID: Optional[int] = None
    m_HeightmapMinimumLODSimplification: Optional[int] = None
    m_IgnoreQualitySettings: Optional[bool] = None
    m_LegacyShininess: Optional[float] = None
    m_LegacySpecular: Optional[ColorRGBA] = None
    m_MaterialType: Optional[int] = None
    m_PreserveTreePrototypeLayers: Optional[bool] = None
    m_RenderingLayerMask: Optional[int] = None
    m_ShadowCastingMode: Optional[int] = None
    m_StaticShadowCaster: Optional[bool] = None
    m_TreeMotionVectorModeOverride: Optional[int] = None
    m_UseDefaultSmoothness: Optional[bool] = None


@unitypy_define
class VideoPlayer(Behaviour):
    m_AspectRatio: int
    m_AudioOutputMode: int
    m_ControlledAudioTrackCount: int
    m_DataSource: int
    m_DirectAudioMutes: List[bool]
    m_DirectAudioVolumes: List[float]
    m_Enabled: int
    m_EnabledAudioTracks: List[bool]
    m_FrameReadyEventEnabled: bool
    m_GameObject: PPtr[GameObject]
    m_Looping: bool
    m_PlayOnAwake: bool
    m_PlaybackSpeed: float
    m_RenderMode: int
    m_SkipOnDrop: bool
    m_TargetAudioSources: List[PPtr[AudioSource]]
    m_TargetCamera: PPtr[Camera]
    m_TargetCameraAlpha: float
    m_TargetMaterialProperty: str
    m_TargetMaterialRenderer: PPtr[Renderer]
    m_TargetTexture: PPtr[RenderTexture]
    m_Url: str
    m_VideoClip: PPtr[VideoClip]
    m_WaitForFirstFrame: bool
    m_TargetCamera3DLayout: Optional[int] = None
    m_TargetMaterialName: Optional[str] = None
    m_TimeReference: Optional[int] = None
    m_TimeUpdateMode: Optional[int] = None
    m_VideoShaders: Optional[List[PPtr[Shader]]] = None


@unitypy_define
class VisualEffect(Behaviour):
    m_Asset: PPtr[VisualEffectAsset]
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_PropertySheet: VFXPropertySheetSerializedBase
    m_ResetSeedOnPlay: Union[bool, int]
    m_StartSeed: int
    m_AllowInstancing: Optional[int] = None
    m_InitialEventName: Optional[str] = None
    m_InitialEventNameOverriden: Optional[int] = None
    m_ReleaseInstanceOnDisable: Optional[int] = None


@unitypy_define
class WindZone(Behaviour):
    m_Enabled: int
    m_GameObject: PPtr[GameObject]
    m_Mode: int
    m_Radius: float
    m_WindMain: float
    m_WindPulseFrequency: float
    m_WindPulseMagnitude: float
    m_WindTurbulence: float


@unitypy_define
class CanvasRenderer(Component):
    m_GameObject: PPtr[GameObject]
    m_CullTransparentMesh: Optional[bool] = None


@unitypy_define
class Collider(Component):
    m_GameObject: Optional[PPtr[GameObject]] = None
    m_MaxLimitX: Optional[float] = None
    m_MaxLimitY: Optional[float] = None
    m_MaxLimitZ: Optional[float] = None
    m_MinLimitX: Optional[float] = None
    m_Type: Optional[int] = None
    m_X: Optional[xform] = None
    m_XMotionType: Optional[int] = None
    m_YMotionType: Optional[int] = None
    m_ZMotionType: Optional[int] = None


@unitypy_define
class BoxCollider(Collider):
    m_Center: Vector3f
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: Union[PPtr[PhysicMaterial], PPtr[PhysicsMaterial]]
    m_Size: Vector3f
    m_ExcludeLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_ProvidesContacts: Optional[bool] = None


@unitypy_define
class CapsuleCollider(Collider):
    m_Center: Vector3f
    m_Direction: int
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_Height: float
    m_IsTrigger: bool
    m_Material: Union[PPtr[PhysicMaterial], PPtr[PhysicsMaterial]]
    m_Radius: float
    m_ExcludeLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_ProvidesContacts: Optional[bool] = None


@unitypy_define
class CharacterController(Collider):
    m_Center: Vector3f
    m_GameObject: PPtr[GameObject]
    m_Height: float
    m_MinMoveDistance: float
    m_Radius: float
    m_SkinWidth: float
    m_SlopeLimit: float
    m_StepOffset: float
    m_Enabled: Optional[bool] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_IsTrigger: Optional[bool] = None
    m_LayerOverridePriority: Optional[int] = None
    m_Material: Optional[Union[PPtr[PhysicMaterial], PPtr[PhysicsMaterial]]] = None
    m_ProvidesContacts: Optional[bool] = None


@unitypy_define
class MeshCollider(Collider):
    m_Convex: bool
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: Union[PPtr[PhysicMaterial], PPtr[PhysicsMaterial]]
    m_Mesh: PPtr[Mesh]
    m_CookingOptions: Optional[int] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_InflateMesh: Optional[bool] = None
    m_LayerOverridePriority: Optional[int] = None
    m_ProvidesContacts: Optional[bool] = None
    m_SkinWidth: Optional[float] = None
    m_SmoothSphereCollisions: Optional[bool] = None


@unitypy_define
class RaycastCollider(Collider):
    m_Center: Vector3f
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Length: float
    m_Material: PPtr[PhysicMaterial]


@unitypy_define
class SphereCollider(Collider):
    m_Center: Vector3f
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_IsTrigger: bool
    m_Material: Union[PPtr[PhysicMaterial], PPtr[PhysicsMaterial]]
    m_Radius: float
    m_ExcludeLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_ProvidesContacts: Optional[bool] = None


@unitypy_define
class TerrainCollider(Collider):
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_TerrainData: PPtr[TerrainData]
    m_CreateTreeColliders: Optional[bool] = None
    m_EnableTreeColliders: Optional[bool] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_IncludeLayers: Optional[BitField] = None
    m_IsTrigger: Optional[bool] = None
    m_LayerOverridePriority: Optional[int] = None
    m_Material: Optional[Union[PPtr[PhysicMaterial], PPtr[PhysicsMaterial]]] = None
    m_ProvidesContacts: Optional[bool] = None


@unitypy_define
class WheelCollider(Collider):
    m_Center: Vector3f
    m_ForwardFriction: WheelFrictionCurve
    m_GameObject: PPtr[GameObject]
    m_Mass: float
    m_Radius: float
    m_SidewaysFriction: WheelFrictionCurve
    m_SuspensionDistance: float
    m_SuspensionSpring: JointSpring
    m_Enabled: Optional[bool] = None
    m_ExcludeLayers: Optional[BitField] = None
    m_ForceAppPointDistance: Optional[float] = None
    m_IncludeLayers: Optional[BitField] = None
    m_LayerOverridePriority: Optional[int] = None
    m_ProvidesContacts: Optional[bool] = None
    m_WheelDampingRate: Optional[float] = None


@unitypy_define
class FakeComponent(Component):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class Joint(Component):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class CharacterJoint(Joint):
    m_Anchor: Vector3f
    m_Axis: Vector3f
    m_BreakForce: float
    m_BreakTorque: float
    m_ConnectedBody: PPtr[Rigidbody]
    m_GameObject: PPtr[GameObject]
    m_HighTwistLimit: SoftJointLimit
    m_LowTwistLimit: SoftJointLimit
    m_Swing1Limit: SoftJointLimit
    m_Swing2Limit: SoftJointLimit
    m_SwingAxis: Vector3f
    m_AutoConfigureConnectedAnchor: Optional[bool] = None
    m_ConnectedAnchor: Optional[Vector3f] = None
    m_ConnectedArticulationBody: Optional[PPtr[ArticulationBody]] = None
    m_ConnectedMassScale: Optional[float] = None
    m_EnableCollision: Optional[bool] = None
    m_EnablePreprocessing: Optional[bool] = None
    m_EnableProjection: Optional[bool] = None
    m_Enabled: Optional[bool] = None
    m_MassScale: Optional[float] = None
    m_ProjectionAngle: Optional[float] = None
    m_ProjectionDistance: Optional[float] = None
    m_SwingLimitSpring: Optional[SoftJointLimitSpring] = None
    m_TwistLimitSpring: Optional[SoftJointLimitSpring] = None


@unitypy_define
class ConfigurableJoint(Joint):
    m_Anchor: Vector3f
    m_AngularXDrive: JointDrive
    m_AngularXMotion: int
    m_AngularYLimit: SoftJointLimit
    m_AngularYMotion: int
    m_AngularYZDrive: JointDrive
    m_AngularZLimit: SoftJointLimit
    m_AngularZMotion: int
    m_Axis: Vector3f
    m_BreakForce: float
    m_BreakTorque: float
    m_ConfiguredInWorldSpace: bool
    m_ConnectedBody: PPtr[Rigidbody]
    m_GameObject: PPtr[GameObject]
    m_HighAngularXLimit: SoftJointLimit
    m_LinearLimit: SoftJointLimit
    m_LowAngularXLimit: SoftJointLimit
    m_ProjectionAngle: float
    m_ProjectionDistance: float
    m_ProjectionMode: int
    m_RotationDriveMode: int
    m_SecondaryAxis: Vector3f
    m_SlerpDrive: JointDrive
    m_TargetAngularVelocity: Vector3f
    m_TargetPosition: Vector3f
    m_TargetRotation: Quaternionf
    m_TargetVelocity: Vector3f
    m_XDrive: JointDrive
    m_XMotion: int
    m_YDrive: JointDrive
    m_YMotion: int
    m_ZDrive: JointDrive
    m_ZMotion: int
    m_AngularXLimitSpring: Optional[SoftJointLimitSpring] = None
    m_AngularYZLimitSpring: Optional[SoftJointLimitSpring] = None
    m_AutoConfigureConnectedAnchor: Optional[bool] = None
    m_ConnectedAnchor: Optional[Vector3f] = None
    m_ConnectedArticulationBody: Optional[PPtr[ArticulationBody]] = None
    m_ConnectedMassScale: Optional[float] = None
    m_EnableCollision: Optional[bool] = None
    m_EnablePreprocessing: Optional[bool] = None
    m_Enabled: Optional[bool] = None
    m_LinearLimitSpring: Optional[SoftJointLimitSpring] = None
    m_MassScale: Optional[float] = None
    m_SwapBodies: Optional[bool] = None


@unitypy_define
class FixedJoint(Joint):
    m_BreakForce: float
    m_BreakTorque: float
    m_ConnectedBody: PPtr[Rigidbody]
    m_GameObject: PPtr[GameObject]
    m_ConnectedArticulationBody: Optional[PPtr[ArticulationBody]] = None
    m_ConnectedMassScale: Optional[float] = None
    m_EnableCollision: Optional[bool] = None
    m_EnablePreprocessing: Optional[bool] = None
    m_Enabled: Optional[bool] = None
    m_MassScale: Optional[float] = None


@unitypy_define
class HingeJoint(Joint):
    m_Anchor: Vector3f
    m_Axis: Vector3f
    m_BreakForce: float
    m_BreakTorque: float
    m_ConnectedBody: PPtr[Rigidbody]
    m_GameObject: PPtr[GameObject]
    m_Limits: JointLimits
    m_Motor: JointMotor
    m_Spring: JointSpring
    m_UseLimits: bool
    m_UseMotor: bool
    m_UseSpring: bool
    m_AutoConfigureConnectedAnchor: Optional[bool] = None
    m_ConnectedAnchor: Optional[Vector3f] = None
    m_ConnectedArticulationBody: Optional[PPtr[ArticulationBody]] = None
    m_ConnectedMassScale: Optional[float] = None
    m_EnableCollision: Optional[bool] = None
    m_EnablePreprocessing: Optional[bool] = None
    m_Enabled: Optional[bool] = None
    m_ExtendedLimits: Optional[bool] = None
    m_MassScale: Optional[float] = None
    m_UseAcceleration: Optional[bool] = None


@unitypy_define
class SpringJoint(Joint):
    m_Anchor: Vector3f
    m_BreakForce: float
    m_BreakTorque: float
    m_ConnectedBody: PPtr[Rigidbody]
    m_Damper: float
    m_GameObject: PPtr[GameObject]
    m_MaxDistance: float
    m_MinDistance: float
    m_Spring: float
    m_AutoConfigureConnectedAnchor: Optional[bool] = None
    m_Axis: Optional[Vector3f] = None
    m_ConnectedAnchor: Optional[Vector3f] = None
    m_ConnectedArticulationBody: Optional[PPtr[ArticulationBody]] = None
    m_ConnectedMassScale: Optional[float] = None
    m_EnableCollision: Optional[bool] = None
    m_EnablePreprocessing: Optional[bool] = None
    m_Enabled: Optional[bool] = None
    m_MassScale: Optional[float] = None
    m_Tolerance: Optional[float] = None


@unitypy_define
class LODGroup(Component):
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LODs: List[LOD]
    m_LocalReferencePoint: Vector3f
    m_Size: float
    m_AnimateCrossFading: Optional[bool] = None
    m_FadeMode: Optional[int] = None
    m_GlobalIlluminationLOD: Optional[int] = None
    m_LastLODIsBillboard: Optional[bool] = None
    m_ScreenRelativeTransitionHeight: Optional[float] = None


@unitypy_define
class MeshFilter(Component):
    m_GameObject: PPtr[GameObject]
    m_Mesh: PPtr[Mesh]


@unitypy_define
class MultiplayerRolesData(Component):
    m_ComponentsRolesMasks: List[ObjectRolePair]
    m_GameObject: PPtr[GameObject]
    m_GameObjectRolesMask: int


@unitypy_define
class OcclusionArea(Component):
    m_Center: Vector3f
    m_GameObject: PPtr[GameObject]
    m_IsViewVolume: bool
    m_Size: Vector3f
    m_IsTargetVolume: Optional[bool] = None
    m_TargetResolution: Optional[int] = None


@unitypy_define
class OcclusionPortal(Component):
    m_Center: Vector3f
    m_GameObject: PPtr[GameObject]
    m_Open: bool
    m_Size: Vector3f


@unitypy_define
class ParticleAnimator(Component):
    Does_Animate_Color: bool
    autodestruct: bool
    colorAnimation_0_: ColorRGBA
    colorAnimation_1_: ColorRGBA
    colorAnimation_2_: ColorRGBA
    colorAnimation_3_: ColorRGBA
    colorAnimation_4_: ColorRGBA
    damping: float
    force: Vector3f
    localRotationAxis: Vector3f
    m_GameObject: PPtr[GameObject]
    rndForce: Vector3f
    sizeGrow: float
    stopSimulation: bool
    worldRotationAxis: Vector3f


@unitypy_define
class ParticleEmitter(Component):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class EllipsoidParticleEmitter(ParticleEmitter):
    Simulate_in_Worldspace: bool
    angularVelocity: float
    emitterVelocityScale: float
    localVelocity: Vector3f
    m_Ellipsoid: Vector3f
    m_Emit: bool
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_MinEmitterRange: float
    m_OneShot: bool
    maxEmission: float
    maxEnergy: float
    maxSize: float
    minEmission: float
    minEnergy: float
    minSize: float
    rndAngularVelocity: float
    rndRotation: bool
    rndVelocity: Vector3f
    tangentVelocity: Vector3f
    worldVelocity: Vector3f


@unitypy_define
class MeshParticleEmitter(ParticleEmitter):
    Simulate_in_Worldspace: bool
    angularVelocity: float
    emitterVelocityScale: float
    localVelocity: Vector3f
    m_Emit: bool
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_InterpolateTriangles: bool
    m_MaxNormalVelocity: float
    m_Mesh: PPtr[Mesh]
    m_MinNormalVelocity: float
    m_OneShot: bool
    m_Systematic: bool
    maxEmission: float
    maxEnergy: float
    maxSize: float
    minEmission: float
    minEnergy: float
    minSize: float
    rndAngularVelocity: float
    rndRotation: bool
    rndVelocity: Vector3f
    tangentVelocity: Vector3f
    worldVelocity: Vector3f


@unitypy_define
class ParticleSystem(Component):
    ClampVelocityModule: ClampVelocityModule
    CollisionModule: CollisionModule
    ColorBySpeedModule: ColorBySpeedModule
    ColorModule: ColorModule
    EmissionModule: EmissionModule
    ForceModule: ForceModule
    InitialModule: InitialModule
    RotationBySpeedModule: RotationBySpeedModule
    RotationModule: RotationModule
    ShapeModule: ShapeModule
    SizeBySpeedModule: SizeBySpeedModule
    SizeModule: SizeModule
    SubModule: SubModule
    UVModule: UVModule
    VelocityModule: VelocityModule
    lengthInSec: float
    looping: bool
    m_GameObject: PPtr[GameObject]
    moveWithTransform: Union[bool, int]
    playOnAwake: bool
    prewarm: bool
    randomSeed: int
    startDelay: Union[MinMaxCurve, float]
    CustomDataModule: Optional[CustomDataModule] = None
    ExternalForcesModule: Optional[ExternalForcesModule] = None
    InheritVelocityModule: Optional[InheritVelocityModule] = None
    LifetimeByEmitterSpeedModule: Optional[LifetimeByEmitterSpeedModule] = None
    LightsModule: Optional[LightsModule] = None
    NoiseModule: Optional[NoiseModule] = None
    TrailModule: Optional[TrailModule] = None
    TriggerModule: Optional[TriggerModule] = None
    autoRandomSeed: Optional[bool] = None
    cullingMode: Optional[int] = None
    emitterVelocityMode: Optional[int] = None
    moveWithCustomTransform: Optional[PPtr[Transform]] = None
    ringBufferLoopRange: Optional[Vector2f] = None
    ringBufferMode: Optional[int] = None
    scalingMode: Optional[int] = None
    simulationSpeed: Optional[float] = None
    speed: Optional[float] = None
    stopAction: Optional[int] = None
    useRigidbodyForVelocity: Optional[bool] = None
    useUnscaledTime: Optional[bool] = None


@unitypy_define
class Pipeline(Component):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class Renderer(Component):
    m_GameObject: PPtr[GameObject]


@unitypy_define
class BillboardRenderer(Renderer):
    m_Billboard: PPtr[BillboardAsset]
    m_CastShadows: int
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapIndexDynamic: int
    m_LightmapTilingOffset: Vector4f
    m_LightmapTilingOffsetDynamic: Vector4f
    m_Materials: List[PPtr[Material]]
    m_ProbeAnchor: PPtr[Transform]
    m_ReceiveShadows: Union[bool, int]
    m_ReflectionProbeUsage: int
    m_SortingOrder: int
    m_StaticBatchRoot: PPtr[Transform]
    m_DynamicOccludee: Optional[int] = None
    m_ForceMeshLod: Optional[int] = None
    m_LightProbeUsage: Optional[int] = None
    m_LightProbeVolumeOverride: Optional[PPtr[GameObject]] = None
    m_MaskInteraction: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_MotionVectors: Optional[int] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_StaticBatchInfo: Optional[StaticBatchInfo] = None
    m_StaticShadowCaster: Optional[int] = None
    m_SubsetIndices: Optional[List[int]] = None
    m_UseLightProbes: Optional[bool] = None


@unitypy_define
class ClothRenderer(Renderer):
    m_CastShadows: bool
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapTilingOffset: Vector4f
    m_Materials: List[PPtr[Material]]
    m_PauseWhenNotVisible: bool
    m_ReceiveShadows: bool
    m_StaticBatchRoot: PPtr[Transform]
    m_SubsetIndices: List[int]
    m_LightProbeAnchor: Optional[PPtr[Transform]] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_SortingOrder: Optional[int] = None
    m_UseLightProbes: Optional[bool] = None


@unitypy_define
class LineRenderer(Renderer):
    m_CastShadows: Union[bool, int]
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapTilingOffset: Vector4f
    m_Materials: List[PPtr[Material]]
    m_Parameters: LineParameters
    m_Positions: List[Vector3f]
    m_ReceiveShadows: Union[bool, int]
    m_StaticBatchRoot: PPtr[Transform]
    m_UseWorldSpace: bool
    m_ApplyActiveColorSpace: Optional[bool] = None
    m_DynamicOccludee: Optional[int] = None
    m_ForceMeshLod: Optional[int] = None
    m_LightProbeAnchor: Optional[PPtr[Transform]] = None
    m_LightProbeUsage: Optional[int] = None
    m_LightProbeVolumeOverride: Optional[PPtr[GameObject]] = None
    m_LightmapIndexDynamic: Optional[int] = None
    m_LightmapTilingOffsetDynamic: Optional[Vector4f] = None
    m_Loop: Optional[bool] = None
    m_MaskInteraction: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_MotionVectors: Optional[int] = None
    m_ProbeAnchor: Optional[PPtr[Transform]] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_ReflectionProbeUsage: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_SortingOrder: Optional[int] = None
    m_StaticBatchInfo: Optional[StaticBatchInfo] = None
    m_StaticShadowCaster: Optional[int] = None
    m_SubsetIndices: Optional[List[int]] = None
    m_UseLightProbes: Optional[bool] = None


@unitypy_define
class RendererFake(LineRenderer):
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
    m_Loop: bool
    m_Materials: List[PPtr[Material]]
    m_MotionVectors: int
    m_Parameters: LineParameters
    m_Positions: List[Vector3f]
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
    m_UseWorldSpace: bool
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingMode: Optional[int] = None


@unitypy_define
class MeshRenderer(Renderer):
    m_CastShadows: Union[bool, int]
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapTilingOffset: Vector4f
    m_Materials: List[PPtr[Material]]
    m_ReceiveShadows: Union[bool, int]
    m_StaticBatchRoot: PPtr[Transform]
    m_AdditionalVertexStreams: Optional[PPtr[Mesh]] = None
    m_DynamicOccludee: Optional[int] = None
    m_EnlightenVertexStream: Optional[PPtr[Mesh]] = None
    m_ForceMeshLod: Optional[int] = None
    m_LightProbeAnchor: Optional[PPtr[Transform]] = None
    m_LightProbeUsage: Optional[int] = None
    m_LightProbeVolumeOverride: Optional[PPtr[GameObject]] = None
    m_LightmapIndexDynamic: Optional[int] = None
    m_LightmapTilingOffsetDynamic: Optional[Vector4f] = None
    m_MaskInteraction: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_MotionVectors: Optional[int] = None
    m_ProbeAnchor: Optional[PPtr[Transform]] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_ReflectionProbeUsage: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_SortingOrder: Optional[int] = None
    m_StaticBatchInfo: Optional[StaticBatchInfo] = None
    m_StaticShadowCaster: Optional[int] = None
    m_SubsetIndices: Optional[List[int]] = None
    m_UseLightProbes: Optional[bool] = None


@unitypy_define
class PanelRenderer(Renderer):
    m_CastShadows: int
    m_DynamicOccludee: int
    m_Enabled: bool
    m_ForceMeshLod: int
    m_GameObject: PPtr[GameObject]
    m_LightProbeUsage: int
    m_LightProbeVolumeOverride: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapIndexDynamic: int
    m_LightmapTilingOffset: Vector4f
    m_LightmapTilingOffsetDynamic: Vector4f
    m_MaskInteraction: int
    m_Materials: List[PPtr[Material]]
    m_MeshLodSelectionBias: float
    m_MotionVectors: int
    m_PanelSettings: PPtr[MonoBehaviour]
    m_ParentUI: PPtr[PanelRenderer]
    m_Pivot: int
    m_PivotReferenceSize: int
    m_Position: int
    m_ProbeAnchor: PPtr[Transform]
    m_RayTraceProcedural: int
    m_RayTracingAccelStructBuildFlags: int
    m_RayTracingAccelStructBuildFlagsOverride: int
    m_RayTracingMode: int
    m_ReceiveShadows: int
    m_ReflectionProbeUsage: int
    m_RendererPriority: int
    m_RenderingLayerMask: int
    m_SmallMeshCulling: int
    m_SortingLayer: int
    m_SortingLayerID: int
    m_SortingOrder: int
    m_StaticBatchInfo: StaticBatchInfo
    m_StaticBatchRoot: PPtr[Transform]
    m_StaticShadowCaster: int
    m_WorldSpaceHeight: float
    m_WorldSpaceSizeMode: int
    m_WorldSpaceWidth: float
    sourceAsset: PPtr[MonoBehaviour]


@unitypy_define
class ParticleRenderer(Renderer):
    UV_Animation: UVAnimation
    m_CameraVelocityScale: float
    m_CastShadows: Union[bool, int]
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LengthScale: float
    m_LightmapIndex: int
    m_LightmapTilingOffset: Vector4f
    m_Materials: List[PPtr[Material]]
    m_MaxParticleSize: float
    m_ReceiveShadows: Union[bool, int]
    m_StaticBatchRoot: PPtr[Transform]
    m_StretchParticles: int
    m_VelocityScale: float
    m_DynamicOccludee: Optional[int] = None
    m_LightProbeAnchor: Optional[PPtr[Transform]] = None
    m_LightProbeUsage: Optional[int] = None
    m_LightProbeVolumeOverride: Optional[PPtr[GameObject]] = None
    m_LightmapIndexDynamic: Optional[int] = None
    m_LightmapTilingOffsetDynamic: Optional[Vector4f] = None
    m_MotionVectors: Optional[int] = None
    m_ProbeAnchor: Optional[PPtr[Transform]] = None
    m_ReflectionProbeUsage: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_SortingOrder: Optional[int] = None
    m_StaticBatchInfo: Optional[StaticBatchInfo] = None
    m_SubsetIndices: Optional[List[int]] = None
    m_UseLightProbes: Optional[bool] = None


@unitypy_define
class ParticleSystemRenderer(Renderer):
    m_CameraVelocityScale: float
    m_CastShadows: Union[bool, int]
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LengthScale: float
    m_LightmapIndex: int
    m_LightmapTilingOffset: Vector4f
    m_Materials: List[PPtr[Material]]
    m_MaxParticleSize: float
    m_Mesh: PPtr[Mesh]
    m_ReceiveShadows: Union[bool, int]
    m_RenderMode: int
    m_SortMode: int
    m_SortingFudge: float
    m_StaticBatchRoot: PPtr[Transform]
    m_VelocityScale: float
    m_AllowRoll: Optional[bool] = None
    m_ApplyActiveColorSpace: Optional[bool] = None
    m_DynamicOccludee: Optional[int] = None
    m_EnableGPUInstancing: Optional[bool] = None
    m_Flip: Optional[Vector3f] = None
    m_ForceMeshLod: Optional[int] = None
    m_FreeformStretching: Optional[bool] = None
    m_LightProbeAnchor: Optional[PPtr[Transform]] = None
    m_LightProbeUsage: Optional[int] = None
    m_LightProbeVolumeOverride: Optional[PPtr[GameObject]] = None
    m_LightmapIndexDynamic: Optional[int] = None
    m_LightmapTilingOffsetDynamic: Optional[Vector4f] = None
    m_MaskInteraction: Optional[int] = None
    m_Mesh1: Optional[PPtr[Mesh]] = None
    m_Mesh2: Optional[PPtr[Mesh]] = None
    m_Mesh3: Optional[PPtr[Mesh]] = None
    m_MeshDistribution: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_MeshWeighting: Optional[float] = None
    m_MeshWeighting1: Optional[float] = None
    m_MeshWeighting2: Optional[float] = None
    m_MeshWeighting3: Optional[float] = None
    m_MinParticleSize: Optional[float] = None
    m_MotionVectors: Optional[int] = None
    m_NormalDirection: Optional[float] = None
    m_Pivot: Optional[Vector3f] = None
    m_ProbeAnchor: Optional[PPtr[Transform]] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_ReflectionProbeUsage: Optional[int] = None
    m_RenderAlignment: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_RotateWithStretchDirection: Optional[bool] = None
    m_ShadowBias: Optional[float] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_SortingOrder: Optional[int] = None
    m_StaticBatchInfo: Optional[StaticBatchInfo] = None
    m_StaticShadowCaster: Optional[int] = None
    m_SubsetIndices: Optional[List[int]] = None
    m_TrailVertexStreams: Optional[List[int]] = None
    m_UseCustomTrailVertexStreams: Optional[bool] = None
    m_UseCustomVertexStreams: Optional[bool] = None
    m_UseLightProbes: Optional[bool] = None
    m_VertexStreamMask: Optional[int] = None
    m_VertexStreams: Optional[List[int]] = None


@unitypy_define
class RenderAs2D(Renderer):
    m_CastShadows: int
    m_DynamicOccludee: int
    m_Enabled: bool
    m_ForceMeshLod: int
    m_GameObject: PPtr[GameObject]
    m_LightProbeUsage: int
    m_LightProbeVolumeOverride: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapIndexDynamic: int
    m_LightmapTilingOffset: Vector4f
    m_LightmapTilingOffsetDynamic: Vector4f
    m_MaskInteraction: int
    m_Materials: List[PPtr[Material]]
    m_MeshLodSelectionBias: float
    m_MotionVectors: int
    m_ProbeAnchor: PPtr[Transform]
    m_RayTraceProcedural: int
    m_RayTracingAccelStructBuildFlags: int
    m_RayTracingAccelStructBuildFlagsOverride: int
    m_RayTracingMode: int
    m_ReceiveShadows: int
    m_ReflectionProbeUsage: int
    m_RendererPriority: int
    m_RenderingLayerMask: int
    m_SmallMeshCulling: int
    m_SortingLayer: int
    m_SortingLayerID: int
    m_SortingOrder: int
    m_StaticBatchInfo: StaticBatchInfo
    m_StaticBatchRoot: PPtr[Transform]
    m_StaticShadowCaster: int
    m_Owner: Optional[PPtr[Component]] = None
    m_OwningSortingGroup: Optional[PPtr[SortingGroup]] = None


@unitypy_define
class SkinnedMeshRenderer(Renderer):
    m_AABB: AABB
    m_Bones: List[PPtr[Transform]]
    m_CastShadows: Union[bool, int]
    m_DirtyAABB: bool
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapTilingOffset: Vector4f
    m_Materials: List[PPtr[Material]]
    m_Mesh: PPtr[Mesh]
    m_Quality: int
    m_ReceiveShadows: Union[bool, int]
    m_StaticBatchRoot: PPtr[Transform]
    m_UpdateWhenOffscreen: bool
    m_BlendShapeWeights: Optional[List[float]] = None
    m_DynamicOccludee: Optional[int] = None
    m_ForceMeshLod: Optional[int] = None
    m_LightProbeAnchor: Optional[PPtr[Transform]] = None
    m_LightProbeUsage: Optional[int] = None
    m_LightProbeVolumeOverride: Optional[PPtr[GameObject]] = None
    m_LightmapIndexDynamic: Optional[int] = None
    m_LightmapTilingOffsetDynamic: Optional[Vector4f] = None
    m_MaskInteraction: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_MotionVectors: Optional[int] = None
    m_ProbeAnchor: Optional[PPtr[Transform]] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_ReflectionProbeUsage: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_RootBone: Optional[PPtr[Transform]] = None
    m_SkinnedMotionVectors: Optional[bool] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_SortingOrder: Optional[int] = None
    m_StaticBatchInfo: Optional[StaticBatchInfo] = None
    m_StaticShadowCaster: Optional[int] = None
    m_SubsetIndices: Optional[List[int]] = None
    m_UseLightProbes: Optional[bool] = None


@unitypy_define
class SpriteMask(Renderer):
    m_BackSortingLayer: int
    m_BackSortingOrder: int
    m_CastShadows: int
    m_Enabled: bool
    m_FrontSortingLayer: int
    m_FrontSortingOrder: int
    m_GameObject: PPtr[GameObject]
    m_IsCustomRangeActive: bool
    m_LightProbeUsage: int
    m_LightProbeVolumeOverride: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapIndexDynamic: int
    m_LightmapTilingOffset: Vector4f
    m_LightmapTilingOffsetDynamic: Vector4f
    m_MaskAlphaCutoff: float
    m_Materials: List[PPtr[Material]]
    m_MotionVectors: int
    m_ProbeAnchor: PPtr[Transform]
    m_ReceiveShadows: int
    m_ReflectionProbeUsage: int
    m_SortingLayer: int
    m_SortingLayerID: int
    m_SortingOrder: int
    m_Sprite: PPtr[Sprite]
    m_StaticBatchInfo: StaticBatchInfo
    m_StaticBatchRoot: PPtr[Transform]
    m_BackSortingLayerID: Optional[int] = None
    m_DynamicOccludee: Optional[int] = None
    m_ForceMeshLod: Optional[int] = None
    m_FrontSortingLayerID: Optional[int] = None
    m_MaskInteraction: Optional[int] = None
    m_MaskSource: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SpriteSortPoint: Optional[int] = None
    m_StaticShadowCaster: Optional[int] = None


@unitypy_define
class SpriteRenderer(Renderer):
    m_CastShadows: Union[bool, int]
    m_Color: ColorRGBA
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapTilingOffset: Vector4f
    m_Materials: List[PPtr[Material]]
    m_ReceiveShadows: Union[bool, int]
    m_SortingOrder: int
    m_Sprite: PPtr[Sprite]
    m_StaticBatchRoot: PPtr[Transform]
    m_AdaptiveModeThreshold: Optional[float] = None
    m_BlendShapeWeights: Optional[List[float]] = None
    m_DrawMode: Optional[int] = None
    m_DynamicOccludee: Optional[int] = None
    m_FlipX: Optional[bool] = None
    m_FlipY: Optional[bool] = None
    m_ForceMeshLod: Optional[int] = None
    m_LightProbeAnchor: Optional[PPtr[Transform]] = None
    m_LightProbeUsage: Optional[int] = None
    m_LightProbeVolumeOverride: Optional[PPtr[GameObject]] = None
    m_LightmapIndexDynamic: Optional[int] = None
    m_LightmapTilingOffsetDynamic: Optional[Vector4f] = None
    m_MaskInteraction: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_MotionVectors: Optional[int] = None
    m_ProbeAnchor: Optional[PPtr[Transform]] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_ReflectionProbeUsage: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_Size: Optional[Vector2f] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_SpriteSortPoint: Optional[int] = None
    m_SpriteTileMode: Optional[int] = None
    m_StaticBatchInfo: Optional[StaticBatchInfo] = None
    m_StaticShadowCaster: Optional[int] = None
    m_SubsetIndices: Optional[List[int]] = None
    m_UseLightProbes: Optional[bool] = None
    m_WasSpriteAssigned: Optional[bool] = None


@unitypy_define
class SpriteShapeRenderer(Renderer):
    m_CastShadows: int
    m_Color: ColorRGBA
    m_DynamicOccludee: int
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightProbeUsage: int
    m_LightProbeVolumeOverride: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapIndexDynamic: int
    m_LightmapTilingOffset: Vector4f
    m_LightmapTilingOffsetDynamic: Vector4f
    m_LocalAABB: AABB
    m_MaskInteraction: int
    m_Materials: List[PPtr[Material]]
    m_MotionVectors: int
    m_ProbeAnchor: PPtr[Transform]
    m_ReceiveShadows: int
    m_ReflectionProbeUsage: int
    m_RenderingLayerMask: int
    m_ShapeTexture: PPtr[Texture2D]
    m_SortingLayer: int
    m_SortingLayerID: int
    m_SortingOrder: int
    m_Sprites: List[PPtr[Sprite]]
    m_StaticBatchInfo: StaticBatchInfo
    m_StaticBatchRoot: PPtr[Transform]
    m_ForceMeshLod: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SpriteSortPoint: Optional[int] = None
    m_StaticShadowCaster: Optional[int] = None


@unitypy_define
class TilemapRenderer(Renderer):
    m_CastShadows: int
    m_ChunkSize: int3_storage
    m_DynamicOccludee: int
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightProbeUsage: int
    m_LightProbeVolumeOverride: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapIndexDynamic: int
    m_LightmapTilingOffset: Vector4f
    m_LightmapTilingOffsetDynamic: Vector4f
    m_MaskInteraction: int
    m_Materials: List[PPtr[Material]]
    m_MaxChunkCount: int
    m_MaxFrameAge: int
    m_MotionVectors: int
    m_ProbeAnchor: PPtr[Transform]
    m_ReceiveShadows: int
    m_ReflectionProbeUsage: int
    m_SortOrder: int
    m_SortingLayer: int
    m_SortingLayerID: int
    m_SortingOrder: int
    m_StaticBatchInfo: StaticBatchInfo
    m_StaticBatchRoot: PPtr[Transform]
    m_ChunkCullingBounds: Optional[Vector3f] = None
    m_DetectChunkCullingBounds: Optional[int] = None
    m_ForceMeshLod: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_Mode: Optional[int] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_SmallMeshCulling: Optional[int] = None
    m_StaticShadowCaster: Optional[int] = None


@unitypy_define
class TrailRenderer(Renderer):
    m_Autodestruct: bool
    m_CastShadows: Union[bool, int]
    m_Enabled: bool
    m_GameObject: PPtr[GameObject]
    m_LightmapIndex: int
    m_LightmapTilingOffset: Vector4f
    m_Materials: List[PPtr[Material]]
    m_MinVertexDistance: float
    m_ReceiveShadows: Union[bool, int]
    m_StaticBatchRoot: PPtr[Transform]
    m_Time: float
    m_ApplyActiveColorSpace: Optional[bool] = None
    m_Colors: Optional[Gradient] = None
    m_DynamicOccludee: Optional[int] = None
    m_Emitting: Optional[bool] = None
    m_EndWidth: Optional[float] = None
    m_ForceMeshLod: Optional[int] = None
    m_LightProbeAnchor: Optional[PPtr[Transform]] = None
    m_LightProbeUsage: Optional[int] = None
    m_LightProbeVolumeOverride: Optional[PPtr[GameObject]] = None
    m_LightmapIndexDynamic: Optional[int] = None
    m_LightmapTilingOffsetDynamic: Optional[Vector4f] = None
    m_MaskInteraction: Optional[int] = None
    m_MeshLodSelectionBias: Optional[float] = None
    m_MotionVectors: Optional[int] = None
    m_Parameters: Optional[LineParameters] = None
    m_ProbeAnchor: Optional[PPtr[Transform]] = None
    m_RayTraceProcedural: Optional[int] = None
    m_RayTracingAccelStructBuildFlags: Optional[int] = None
    m_RayTracingAccelStructBuildFlagsOverride: Optional[int] = None
    m_RayTracingMode: Optional[int] = None
    m_ReflectionProbeUsage: Optional[int] = None
    m_RendererPriority: Optional[int] = None
    m_RenderingLayerMask: Optional[int] = None
    m_SmallMeshCulling: Optional[int] = None
    m_SortingLayer: Optional[int] = None
    m_SortingLayerID: Optional[int] = None
    m_SortingOrder: Optional[int] = None
    m_StartWidth: Optional[float] = None
    m_StaticBatchInfo: Optional[StaticBatchInfo] = None
    m_StaticShadowCaster: Optional[int] = None
    m_SubsetIndices: Optional[List[int]] = None
    m_UseLightProbes: Optional[bool] = None


