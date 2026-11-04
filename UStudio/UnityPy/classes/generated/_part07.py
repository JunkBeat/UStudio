# type: ignore
from __future__ import annotations

from ._common import ABC, unitypy_define
from ._part04 import GlobalGameManager, LevelGameManager


@unitypy_define
class PhysicsJobOptions2D:
    m_ClearBodyForcesPerJob: int
    m_ClearFlagsPerJob: int
    m_CollideContactsPerJob: int
    m_FindNearestContactsPerJob: int
    m_InterpolationPosesPerJob: int
    m_IslandSolverBodiesPerJob: int
    m_IslandSolverBodyCostScale: int
    m_IslandSolverContactCostScale: int
    m_IslandSolverContactsPerJob: int
    m_IslandSolverCostThreshold: int
    m_IslandSolverJointCostScale: int
    m_NewContactsPerJob: int
    m_SyncContinuousFixturesPerJob: int
    m_SyncDiscreteFixturesPerJob: int
    m_UpdateTriggerContactsPerJob: int
    m_UseConsistencySorting: Optional[bool] = None
    m_UseMultithreading: Optional[bool] = None
    useConsistencySorting: Optional[bool] = None
    useMultithreading: Optional[bool] = None


@unitypy_define
class PhysicsShape:
    m_AdjacentEnd: Vector2f
    m_AdjacentStart: Vector2f
    m_Radius: float
    m_ShapeType: int
    m_UseAdjacentEnd: int
    m_UseAdjacentStart: int
    m_VertexCount: int
    m_VertexStartIndex: int


@unitypy_define
class PhysicsShapeGroup2D:
    m_Shapes: List[PhysicsShape]
    m_Vertices: List[Vector2f]


@unitypy_define
class PlatformSettings:
    m_AllowsAlphaSplitting: bool
    m_BuildTarget: str
    m_CompressionQuality: int
    m_CrunchedCompression: bool
    m_MaxTextureSize: int
    m_Overridden: bool
    m_TextureCompression: int
    m_TextureFormat: int
    m_ResizeAlgorithm: Optional[int] = None


@unitypy_define
class PlatformSettingsData:
    settings: List[Tuple[str, str]]
    enabled: Optional[bool] = None


@unitypy_define
class PlatformShaderDefines:
    defines_Tier1: List[int]
    defines_Tier2: List[int]
    defines_Tier3: List[int]
    shaderPlatform: int


@unitypy_define
class PlatformShaderSettings:
    useCascadedShadowMaps: Optional[bool] = None
    useScreenSpaceShadows: Optional[bool] = None


@unitypy_define
class PluginImportOutput:
    dllType: Optional[int] = None
    pluginType: Optional[int] = None
    scriptingRuntimeVersion: Optional[int] = None


@unitypy_define
class Polygon2D(ABC):
    m_Paths: Optional[List[List[Vector2f]]] = None


@unitypy_define
class PrefabModification:
    m_Modifications: List[PropertyModification]
    m_RemovedComponents: Union[List[PPtr[Component]], List[PPtr[Object]]]
    m_TransformParent: PPtr[Transform]
    m_AddedComponents: Optional[List[AddedComponent]] = None
    m_AddedGameObjects: Optional[List[AddedGameObject]] = None
    m_RemovedGameObjects: Optional[List[PPtr[GameObject]]] = None


@unitypy_define
class PresetType:
    m_ManagedTypeFallback: str
    m_ManagedTypePPtr: PPtr[MonoScript]
    m_NativeTypeID: int


@unitypy_define
class PreviewData:
    m_CompSize: int
    m_OrigSize: int
    m_PreviewData: List[float]


@unitypy_define
class ProbeSetIndex:
    m_Hash: Hash128
    m_Offset: int
    m_Size: int


@unitypy_define
class ProbeSetTetrahedralization:
    m_HullRays: List[Vector3f]
    m_Tetrahedra: List[Tetrahedron]


@unitypy_define
class ProceduralMaterialInformation:
    m_Offset: Vector2f
    m_Scale: Vector2f
    m_AnimationUpdateRate: Optional[int] = None
    m_GenerateAllOutputs: Optional[int] = None
    m_GenerateMipmaps: Optional[bool] = None
    m_GeneratedAtLoading: Optional[int] = None


@unitypy_define
class ProceduralTextureAssignment:
    baseUID: int
    material: PPtr[ProceduralMaterial]
    shaderProp: Union[FastPropertyName, str]


@unitypy_define
class ProgramParameters:
    m_BufferParams: List[BufferBindingParameter]
    m_ConstantBufferBindings: List[BufferBindingParameter]
    m_ConstantBuffers: List[ConstantBufferParameter]
    m_Samplers: List[SamplerParameter]
    m_TextureParams: List[TextureParameter]
    m_UAVParams: List[UAVParameter]
    m_MatrixParams: Optional[List[MatrixParameter]] = None
    m_SpecializationConstantParams: Optional[List[SpecializationConstantParameter]] = None
    m_VectorParams: Optional[List[VectorParameter]] = None


@unitypy_define
class PropertyModification:
    objectReference: PPtr[Object]
    propertyPath: str
    target: PPtr[Object]
    value: str


@unitypy_define
class PropertyModificationsTargetTestNativeObject:
    m_FloatValue: float
    m_IntegerValue: int


@unitypy_define
class QualitySetting:
    anisotropicTextures: int
    antiAliasing: int
    pixelLightCount: int
    shadowCascades: int
    shadowDistance: float
    shadowProjection: int
    shadowResolution: int
    shadows: int
    softParticles: bool
    softVegetation: bool
    vSyncCount: int
    adaptiveVsync: Optional[bool] = None
    adaptiveVsyncExtraA: Optional[int] = None
    adaptiveVsyncExtraB: Optional[int] = None
    asyncUploadBufferSize: Optional[int] = None
    asyncUploadPersistentBuffer: Optional[bool] = None
    asyncUploadTimeSlice: Optional[int] = None
    billboardsFaceCameraPosition: Optional[bool] = None
    blendWeights: Optional[int] = None
    customRenderPipeline: Optional[PPtr[MonoBehaviour]] = None
    enableLODCrossFade: Optional[bool] = None
    globalTextureMipmapLimit: Optional[int] = None
    lodBias: Optional[float] = None
    maximumLODLevel: Optional[int] = None
    meshLodThreshold: Optional[float] = None
    name: Optional[str] = None
    particleRaycastBudget: Optional[int] = None
    realtimeGICPUUsage: Optional[int] = None
    realtimeReflectionProbes: Optional[bool] = None
    resolutionScalingFixedDPIFactor: Optional[float] = None
    shadowCascade2Split: Optional[float] = None
    shadowCascade4Split: Optional[Vector3f] = None
    shadowNearPlaneOffset: Optional[float] = None
    shadowmaskMode: Optional[int] = None
    skinWeights: Optional[int] = None
    streamingMipmapsActive: Optional[bool] = None
    streamingMipmapsAddAllCameras: Optional[bool] = None
    streamingMipmapsMaxFileIORequests: Optional[int] = None
    streamingMipmapsMaxLevelReduction: Optional[int] = None
    streamingMipmapsMemoryBudget: Optional[float] = None
    streamingMipmapsRenderersPerFrame: Optional[int] = None
    terrainBasemapDistance: Optional[float] = None
    terrainBillboardStart: Optional[float] = None
    terrainDetailDensityScale: Optional[float] = None
    terrainDetailDistance: Optional[float] = None
    terrainFadeLength: Optional[float] = None
    terrainMaxTrees: Optional[int] = None
    terrainPixelError: Optional[float] = None
    terrainQualityOverrides: Optional[int] = None
    terrainTreeDistance: Optional[float] = None
    textureMipmapLimitSettings: Optional[List[MipmapLimitSettings]] = None
    textureQuality: Optional[int] = None
    useLegacyDetailDistribution: Optional[bool] = None


@unitypy_define
class QuaternionCurve:
    curve: AnimationCurve
    path: str


@unitypy_define
class RationalTime:
    m_Count: int
    m_Rate: TicksPerSecond


@unitypy_define
class RayTracingShaderBuiltinSampler:
    bindPoint: int
    sampler: int


@unitypy_define
class RayTracingShaderConstantBuffer:
    byteSize: int
    name: str
    params: List[RayTracingShaderParam]
    hash: Optional[int] = None


@unitypy_define
class RayTracingShaderFunctionDesc:
    attributeSizeInBytes: int
    identifier: RayTracingShaderID
    payloadSizeInBytes: int


@unitypy_define
class RayTracingShaderID:
    name: str
    type: int


@unitypy_define
class RayTracingShaderParam:
    arraySize: int
    colCount: int
    name: str
    offset: int
    rowCount: int
    dataSize: Optional[int] = None
    dataType: Optional[int] = None
    propertySheetType: Optional[int] = None
    type: Optional[int] = None


@unitypy_define
class RayTracingShaderPlatformVariant:
    dynamicKeywords: List[str]
    editorOnlyVariant: bool
    globalKeywords: List[str]
    localKeywords: List[str]
    targetRenderer: int
    uniqueVariants: List[RayTracingShaderReflectionData]
    variantIndices: List[Tuple[str, int]]


@unitypy_define
class RayTracingShaderReflectionData:
    code: List[int]
    functions: List[RayTracingShaderFunctionDesc]
    globalResources: RayTracingShaderResources
    hasErrors: bool
    localResources: RayTracingShaderResources
    codeHash: Optional[int] = None
    precompiled: Optional[List[int]] = None
    requirements: Optional[int] = None


@unitypy_define
class RayTracingShaderResource:
    bindPoint: int
    name: str
    rayGenMask: int
    samplerBindPoint: int
    texDimension: int
    arraySize: Optional[int] = None
    multisampled: Optional[bool] = None
    resType: Optional[int] = None


@unitypy_define
class RayTracingShaderResources:
    builtinSamplers: List[RayTracingShaderBuiltinSampler]
    constantBuffers: List[RayTracingShaderResource]
    constantBuffersDesc: List[RayTracingShaderConstantBuffer]
    inputBuffers: List[RayTracingShaderResource]
    outputBuffers: List[RayTracingShaderResource]
    textures: List[RayTracingShaderResource]


@unitypy_define
class RayTracingShaderVariant:
    resourceReflectionData: RayTracingShaderReflectionData
    targetRenderer: int
    editorOnlyVariant: Optional[bool] = None


@unitypy_define
class Rectf:
    height: float
    width: float
    x: float
    y: float


@unitypy_define
class ReflectedFunction:
    m_Hints: List[Hint]
    m_Name: str
    m_Parameters: List[ReflectedParameter]
    m_ReturnTypeName: str
    m_Body: Optional[str] = None
    m_Namespace: Optional[List[str]] = None


@unitypy_define
class ReflectedParameter:
    m_Direction: int
    m_Hints: List[Hint]
    m_Name: str
    m_TypeName: str


@unitypy_define
class RenderManager(GlobalGameManager):
    pass


@unitypy_define
class RenderPassInfo:
    attachmentCount: int
    attachments: List[AttachmentInfo]
    depthAttachmentIndex: int
    multiviewCount: int
    sampleCount: int
    shadingRateIndex: int
    subPassCount: int
    subPasses: List[SubPassDescriptor]
    foveationImageIndex: Optional[int] = None
    hasEyeTexture: Optional[bool] = None


@unitypy_define
class RenderStateBlock:
    blendState: GfxBlendState
    depthState: GfxDepthState
    mask: int
    rasterState: GfxRasterState
    stencilRef: int
    stencilState: GfxStencilState


@unitypy_define
class RenderStateInfo:
    renderState: RenderStateBlock


@unitypy_define
class RendererData:
    lightmapIndex: int
    lightmapIndexDynamic: int
    lightmapST: Vector4f
    lightmapSTDynamic: Vector4f
    terrainChunkDynamicUVST: Vector4f
    terrainDynamicUVST: Vector4f
    uvMesh: PPtr[Mesh]
    explicitProbeSetHash: Optional[Hash128] = None


@unitypy_define
class ResourceManager_Dependency:
    m_Dependencies: List[PPtr[Object]]
    m_Object: PPtr[Object]


@unitypy_define
class RippleGroup:
    m_afDirectional_0: float
    m_afDirectional_1: float
    m_afDirectional_10: float
    m_afDirectional_11: float
    m_afDirectional_12: float
    m_afDirectional_13: float
    m_afDirectional_14: float
    m_afDirectional_15: float
    m_afDirectional_16: float
    m_afDirectional_17: float
    m_afDirectional_18: float
    m_afDirectional_19: float
    m_afDirectional_2: float
    m_afDirectional_3: float
    m_afDirectional_4: float
    m_afDirectional_5: float
    m_afDirectional_6: float
    m_afDirectional_7: float
    m_afDirectional_8: float
    m_afDirectional_9: float
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
    m_afPlanar_0: float
    m_afPlanar_1: float
    m_afPlanar_10: float
    m_afPlanar_11: float
    m_afPlanar_12: float
    m_afPlanar_13: float
    m_afPlanar_14: float
    m_afPlanar_15: float
    m_afPlanar_16: float
    m_afPlanar_17: float
    m_afPlanar_18: float
    m_afPlanar_19: float
    m_afPlanar_2: float
    m_afPlanar_3: float
    m_afPlanar_4: float
    m_afPlanar_5: float
    m_afPlanar_6: float
    m_afPlanar_7: float
    m_afPlanar_8: float
    m_afPlanar_9: float
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
    m_fIndependence: float
    m_fShimmer: float


@unitypy_define
class RootMotionData(ABC):
    pass


@unitypy_define
class RotationBySpeedModule:
    curve: MinMaxCurve
    enabled: bool
    range: Vector2f
    separateAxes: Optional[bool] = None
    x: Optional[MinMaxCurve] = None
    y: Optional[MinMaxCurve] = None


@unitypy_define
class RotationModule:
    curve: MinMaxCurve
    enabled: bool
    separateAxes: Optional[bool] = None
    x: Optional[MinMaxCurve] = None
    y: Optional[MinMaxCurve] = None


@unitypy_define
class SBranchWindLevel:
    m_afDirectionAdherence_0: float
    m_afDirectionAdherence_1: float
    m_afDirectionAdherence_2: float
    m_afDirectionAdherence_3: float
    m_afDirectionAdherence_4: float
    m_afDirectionAdherence_5: float
    m_afDirectionAdherence_6: float
    m_afDirectionAdherence_7: float
    m_afDirectionAdherence_8: float
    m_afDirectionAdherence_9: float
    m_afDistance_0: float
    m_afDistance_1: float
    m_afDistance_2: float
    m_afDistance_3: float
    m_afDistance_4: float
    m_afDistance_5: float
    m_afDistance_6: float
    m_afDistance_7: float
    m_afDistance_8: float
    m_afDistance_9: float
    m_afWhip_0: float
    m_afWhip_1: float
    m_afWhip_2: float
    m_afWhip_3: float
    m_afWhip_4: float
    m_afWhip_5: float
    m_afWhip_6: float
    m_afWhip_7: float
    m_afWhip_8: float
    m_afWhip_9: float
    m_fTurbulence: float
    m_fTwitch: float
    m_fTwitchFreqScale: float


@unitypy_define
class SParams:
    BranchLevel1: SBranchWindLevel
    BranchLevel2: SBranchWindLevel
    LeafGroup1: SWindGroup
    LeafGroup2: SWindGroup
    Oscillation0_0: float
    Oscillation0_1: float
    Oscillation0_2: float
    Oscillation0_3: float
    Oscillation0_4: float
    Oscillation0_5: float
    Oscillation0_6: float
    Oscillation0_7: float
    Oscillation0_8: float
    Oscillation0_9: float
    Oscillation1_0: float
    Oscillation1_1: float
    Oscillation1_2: float
    Oscillation1_3: float
    Oscillation1_4: float
    Oscillation1_5: float
    Oscillation1_6: float
    Oscillation1_7: float
    Oscillation1_8: float
    Oscillation1_9: float
    Oscillation2_0: float
    Oscillation2_1: float
    Oscillation2_2: float
    Oscillation2_3: float
    Oscillation2_4: float
    Oscillation2_5: float
    Oscillation2_6: float
    Oscillation2_7: float
    Oscillation2_8: float
    Oscillation2_9: float
    Oscillation3_0: float
    Oscillation3_1: float
    Oscillation3_2: float
    Oscillation3_3: float
    Oscillation3_4: float
    Oscillation3_5: float
    Oscillation3_6: float
    Oscillation3_7: float
    Oscillation3_8: float
    Oscillation3_9: float
    Oscillation4_0: float
    Oscillation4_1: float
    Oscillation4_2: float
    Oscillation4_3: float
    Oscillation4_4: float
    Oscillation4_5: float
    Oscillation4_6: float
    Oscillation4_7: float
    Oscillation4_8: float
    Oscillation4_9: float
    Oscillation5_0: float
    Oscillation5_1: float
    Oscillation5_2: float
    Oscillation5_3: float
    Oscillation5_4: float
    Oscillation5_5: float
    Oscillation5_6: float
    Oscillation5_7: float
    Oscillation5_8: float
    Oscillation5_9: float
    Oscillation6_0: float
    Oscillation6_1: float
    Oscillation6_2: float
    Oscillation6_3: float
    Oscillation6_4: float
    Oscillation6_5: float
    Oscillation6_6: float
    Oscillation6_7: float
    Oscillation6_8: float
    Oscillation6_9: float
    Oscillation7_0: float
    Oscillation7_1: float
    Oscillation7_2: float
    Oscillation7_3: float
    Oscillation7_4: float
    Oscillation7_5: float
    Oscillation7_6: float
    Oscillation7_7: float
    Oscillation7_8: float
    Oscillation7_9: float
    Oscillation8_0: float
    Oscillation8_1: float
    Oscillation8_2: float
    Oscillation8_3: float
    Oscillation8_4: float
    Oscillation8_5: float
    Oscillation8_6: float
    Oscillation8_7: float
    Oscillation8_8: float
    Oscillation8_9: float
    Oscillation9_0: float
    Oscillation9_1: float
    Oscillation9_2: float
    Oscillation9_3: float
    Oscillation9_4: float
    Oscillation9_5: float
    Oscillation9_6: float
    Oscillation9_7: float
    Oscillation9_8: float
    Oscillation9_9: float
    m_afFrondRippleDistance_0: float
    m_afFrondRippleDistance_1: float
    m_afFrondRippleDistance_2: float
    m_afFrondRippleDistance_3: float
    m_afFrondRippleDistance_4: float
    m_afFrondRippleDistance_5: float
    m_afFrondRippleDistance_6: float
    m_afFrondRippleDistance_7: float
    m_afFrondRippleDistance_8: float
    m_afFrondRippleDistance_9: float
    m_afGlobalDirectionAdherence_0: float
    m_afGlobalDirectionAdherence_1: float
    m_afGlobalDirectionAdherence_2: float
    m_afGlobalDirectionAdherence_3: float
    m_afGlobalDirectionAdherence_4: float
    m_afGlobalDirectionAdherence_5: float
    m_afGlobalDirectionAdherence_6: float
    m_afGlobalDirectionAdherence_7: float
    m_afGlobalDirectionAdherence_8: float
    m_afGlobalDirectionAdherence_9: float
    m_afGlobalDistance_0: float
    m_afGlobalDistance_1: float
    m_afGlobalDistance_2: float
    m_afGlobalDistance_3: float
    m_afGlobalDistance_4: float
    m_afGlobalDistance_5: float
    m_afGlobalDistance_6: float
    m_afGlobalDistance_7: float
    m_afGlobalDistance_8: float
    m_afGlobalDistance_9: float
    m_fAnchorDistanceScale: float
    m_fAnchorOffset: float
    m_fDirectionResponse: float
    m_fFrondRippleLightingScalar: float
    m_fFrondRippleTile: float
    m_fGlobalHeight: float
    m_fGlobalHeightExponent: float
    m_fGustDurationMax: float
    m_fGustDurationMin: float
    m_fGustFallScalar: float
    m_fGustFrequency: float
    m_fGustRiseScalar: float
    m_fGustStrengthMax: float
    m_fGustStrengthMin: float
    m_fRollingBranchFieldMin: float
    m_fRollingBranchLightingAdjust: float
    m_fRollingBranchVerticalOffset: float
    m_fRollingLeafRippleMin: float
    m_fRollingLeafTumbleMin: float
    m_fRollingNoisePeriod: float
    m_fRollingNoiseSize: float
    m_fRollingNoiseSpeed: float
    m_fRollingNoiseTurbulence: float
    m_fRollingNoiseTwist: float
    m_fStrengthResponse: float


@unitypy_define
class SWindGroup:
    m_afRippleDistance_0: float
    m_afRippleDistance_1: float
    m_afRippleDistance_2: float
    m_afRippleDistance_3: float
    m_afRippleDistance_4: float
    m_afRippleDistance_5: float
    m_afRippleDistance_6: float
    m_afRippleDistance_7: float
    m_afRippleDistance_8: float
    m_afRippleDistance_9: float
    m_afTumbleDirectionAdherence_0: float
    m_afTumbleDirectionAdherence_1: float
    m_afTumbleDirectionAdherence_2: float
    m_afTumbleDirectionAdherence_3: float
    m_afTumbleDirectionAdherence_4: float
    m_afTumbleDirectionAdherence_5: float
    m_afTumbleDirectionAdherence_6: float
    m_afTumbleDirectionAdherence_7: float
    m_afTumbleDirectionAdherence_8: float
    m_afTumbleDirectionAdherence_9: float
    m_afTumbleFlip_0: float
    m_afTumbleFlip_1: float
    m_afTumbleFlip_2: float
    m_afTumbleFlip_3: float
    m_afTumbleFlip_4: float
    m_afTumbleFlip_5: float
    m_afTumbleFlip_6: float
    m_afTumbleFlip_7: float
    m_afTumbleFlip_8: float
    m_afTumbleFlip_9: float
    m_afTumbleTwist_0: float
    m_afTumbleTwist_1: float
    m_afTumbleTwist_2: float
    m_afTumbleTwist_3: float
    m_afTumbleTwist_4: float
    m_afTumbleTwist_5: float
    m_afTumbleTwist_6: float
    m_afTumbleTwist_7: float
    m_afTumbleTwist_8: float
    m_afTumbleTwist_9: float
    m_afTwitchThrow_0: float
    m_afTwitchThrow_1: float
    m_afTwitchThrow_2: float
    m_afTwitchThrow_3: float
    m_afTwitchThrow_4: float
    m_afTwitchThrow_5: float
    m_afTwitchThrow_6: float
    m_afTwitchThrow_7: float
    m_afTwitchThrow_8: float
    m_afTwitchThrow_9: float
    m_fLeewardScalar: float
    m_fRollMaxScale: float
    m_fRollMinScale: float
    m_fRollSeparation: float
    m_fRollSpeed: float
    m_fTwitchSharpness: float


@unitypy_define
class SampleSettings:
    compressionFormat: int
    conversionMode: int
    loadType: int
    quality: float
    sampleRateOverride: int
    sampleRateSetting: int
    preloadAudioData: Optional[bool] = None


@unitypy_define
class SamplerParameter:
    sampler: int
    bindPoint: Optional[int] = None
    m_Binding: Optional[Binding] = None


@unitypy_define
class Scene(LevelGameManager):
    enabled: Optional[bool] = None
    guid: Optional[GUID] = None
    m_PVSData: Optional[List[int]] = None
    m_PVSObjectsArray: Optional[List[PPtr[Renderer]]] = None
    m_PVSPortalsArray: Optional[List[PPtr[OcclusionPortal]]] = None
    m_QueryMode: Optional[int] = None
    path: Optional[str] = None


@unitypy_define
class SceneDataContainer:
    m_SceneData: List[Tuple[SceneIdentifier, HierarchicalSceneData]]


@unitypy_define
class SceneIdentifier:
    guid: GUID
    handle: Union[UnitySceneHandle, int]


@unitypy_define
class SceneObjectIdentifier:
    targetObject: int
    targetPrefab: int


@unitypy_define
class SceneSettings(LevelGameManager):
    m_PVSData: List[int]
    m_PVSObjectsArray: List[PPtr[Renderer]]
    m_PVSPortalsArray: List[PPtr[OcclusionPortal]]
    m_QueryMode: Optional[int] = None


@unitypy_define
class SceneVisibilityData:
    m_SceneGUID: GUID


@unitypy_define
class ScriptMapper(GlobalGameManager):
    m_Shaders: NameToObjectMap
    m_PreloadShaders: Optional[bool] = None


@unitypy_define
class SecondarySpriteTexture:
    name: str
    texture: PPtr[Texture2D]


@unitypy_define
class SecondaryTextureSettings:
    platformSettings: List[TextureImporterPlatformSettings]
    sRGB: Optional[bool] = None


@unitypy_define
class SelectorStateConstant:
    m_FullPathID: int
    m_IsEntry: bool
    m_TransitionConstantArray: List[OffsetPtr]


@unitypy_define
class SelectorTransitionConstant:
    m_ConditionConstantArray: List[OffsetPtr]
    m_Destination: int


@unitypy_define
class SerializedCustomEditorForRenderPipeline:
    customEditorName: str
    renderPipelineType: str


@unitypy_define
class SerializedPass:
    m_HasInstancingVariant: bool
    m_Name: str
    m_NameIndices: List[Tuple[str, int]]
    m_ProgramMask: int
    m_State: SerializedShaderState
    m_Tags: SerializedTagMap
    m_TextureName: str
    m_Type: int
    m_UseName: str
    progDomain: SerializedProgram
    progFragment: SerializedProgram
    progGeometry: SerializedProgram
    progHull: SerializedProgram
    progVertex: SerializedProgram
    m_EditorDataHash: Optional[List[Hash128]] = None
    m_GlobalKeywordMask: Optional[List[int]] = None
    m_HasProceduralInstancingVariant: Optional[bool] = None
    m_LocalKeywordMask: Optional[List[int]] = None
    m_Platforms: Optional[List[int]] = None
    m_SerializedDynamicBranchKeywordMask: Optional[List[int]] = None
    m_SerializedKeywordStateMask: Optional[List[int]] = None
    progRayTracing: Optional[SerializedProgram] = None


@unitypy_define
class SerializedPlayerSubProgram:
    m_BlobIndex: int
    m_GpuProgramType: int
    m_KeywordIndices: List[int]
    m_ShaderRequirements: int


@unitypy_define
class SerializedProgram:
    m_SubPrograms: List[SerializedSubProgram]
    m_CommonParameters: Optional[Union[ProgramParameters, SerializedProgramParameters]] = None
    m_ParameterBlobIndices: Optional[List[List[int]]] = None
    m_PlayerSubPrograms: Optional[List[List[SerializedPlayerSubProgram]]] = None
    m_SerializedKeywordStateMask: Optional[List[int]] = None


@unitypy_define
class SerializedProgramParameters:
    m_BufferParams: List[BufferBinding]
    m_ConstantBufferBindings: List[BufferBinding]
    m_ConstantBuffers: List[ConstantBuffer]
    m_MatrixParams: List[MatrixParameter]
    m_Samplers: List[SamplerParameter]
    m_TextureParams: List[TextureParameter]
    m_UAVParams: List[UAVParameter]
    m_VectorParams: List[VectorParameter]


@unitypy_define
class SerializedProperties:
    m_Props: List[SerializedProperty]


@unitypy_define
class SerializedProperty:
    m_Attributes: List[str]
    m_DefTexture: SerializedTextureProperty
    m_DefValue_0_: float
    m_DefValue_1_: float
    m_DefValue_2_: float
    m_DefValue_3_: float
    m_Description: str
    m_Flags: int
    m_Name: str
    m_Type: int


@unitypy_define
class SerializedShader:
    m_CustomEditorName: str
    m_Dependencies: List[SerializedShaderDependency]
    m_DisableNoSubshadersMessage: bool
    m_FallbackName: str
    m_Name: str
    m_PropInfo: SerializedProperties
    m_SubShaders: List[SerializedSubShader]
    m_CustomEditorForRenderPipelines: Optional[List[SerializedCustomEditorForRenderPipeline]] = None
    m_KeywordFlags: Optional[List[int]] = None
    m_KeywordNames: Optional[List[str]] = None


@unitypy_define
class SerializedShaderDependency:
    from_: str
    to: str


@unitypy_define
class SerializedShaderFloatValue:
    name: Union[FastPropertyName, str]
    val: float


@unitypy_define
class SerializedShaderRTBlendState:
    blendOp: SerializedShaderFloatValue
    blendOpAlpha: SerializedShaderFloatValue
    colMask: SerializedShaderFloatValue
    destBlend: SerializedShaderFloatValue
    destBlendAlpha: SerializedShaderFloatValue
    srcBlend: SerializedShaderFloatValue
    srcBlendAlpha: SerializedShaderFloatValue


@unitypy_define
class SerializedShaderState:
    alphaToMask: SerializedShaderFloatValue
    culling: SerializedShaderFloatValue
    fogColor: SerializedShaderVectorValue
    fogDensity: SerializedShaderFloatValue
    fogEnd: SerializedShaderFloatValue
    fogMode: int
    fogStart: SerializedShaderFloatValue
    gpuProgramID: int
    lighting: bool
    m_LOD: int
    m_Name: str
    m_Tags: SerializedTagMap
    offsetFactor: SerializedShaderFloatValue
    offsetUnits: SerializedShaderFloatValue
    rtBlend0: SerializedShaderRTBlendState
    rtBlend1: SerializedShaderRTBlendState
    rtBlend2: SerializedShaderRTBlendState
    rtBlend3: SerializedShaderRTBlendState
    rtBlend4: SerializedShaderRTBlendState
    rtBlend5: SerializedShaderRTBlendState
    rtBlend6: SerializedShaderRTBlendState
    rtBlend7: SerializedShaderRTBlendState
    rtSeparateBlend: bool
    stencilOp: SerializedStencilOp
    stencilOpBack: SerializedStencilOp
    stencilOpFront: SerializedStencilOp
    stencilReadMask: SerializedShaderFloatValue
    stencilRef: SerializedShaderFloatValue
    stencilWriteMask: SerializedShaderFloatValue
    zTest: SerializedShaderFloatValue
    zWrite: SerializedShaderFloatValue
    conservative: Optional[SerializedShaderFloatValue] = None
    zClip: Optional[SerializedShaderFloatValue] = None


@unitypy_define
class SerializedShaderVectorValue:
    name: Union[FastPropertyName, str]
    w: SerializedShaderFloatValue
    x: SerializedShaderFloatValue
    y: SerializedShaderFloatValue
    z: SerializedShaderFloatValue


@unitypy_define
class SerializedStencilOp:
    comp: SerializedShaderFloatValue
    fail: SerializedShaderFloatValue
    pass_: SerializedShaderFloatValue
    zFail: SerializedShaderFloatValue


@unitypy_define
class SerializedSubProgram:
    m_BlobIndex: int
    m_Channels: ParserBindChannels
    m_GpuProgramType: int
    m_ShaderHardwareTier: int
    m_BufferParams: Optional[List[BufferBinding]] = None
    m_ConstantBufferBindings: Optional[List[BufferBinding]] = None
    m_ConstantBuffers: Optional[List[ConstantBuffer]] = None
    m_GlobalKeywordIndices: Optional[List[int]] = None
    m_KeywordIndices: Optional[List[int]] = None
    m_LocalKeywordIndices: Optional[List[int]] = None
    m_MatrixParams: Optional[List[MatrixParameter]] = None
    m_Parameters: Optional[Union[ProgramParameters, SerializedProgramParameters]] = None
    m_Samplers: Optional[List[SamplerParameter]] = None
    m_ShaderRequirements: Optional[int] = None
    m_TextureParams: Optional[List[TextureParameter]] = None
    m_UAVParams: Optional[List[UAVParameter]] = None
    m_VectorParams: Optional[List[VectorParameter]] = None


@unitypy_define
class SerializedSubShader:
    m_LOD: int
    m_Passes: List[SerializedPass]
    m_Tags: SerializedTagMap


@unitypy_define
class SerializedTagMap:
    tags: List[Tuple[str, str]]


@unitypy_define
class SerializedTextureProperty:
    m_DefaultName: str
    m_TexDim: int


@unitypy_define
class ShaderBindChannel:
    source: int
    target: int


@unitypy_define
class ShaderInfo:
    variants: List[VariantInfo]


@unitypy_define
class ShadowSettings:
    m_Bias: float
    m_Resolution: int
    m_Strength: float
    m_Type: int
    m_CullingMatrixOverride: Optional[Matrix4x4f] = None
    m_CustomResolution: Optional[int] = None
    m_NearPlane: Optional[float] = None
    m_NormalBias: Optional[float] = None
    m_Softness: Optional[float] = None
    m_SoftnessFade: Optional[float] = None
    m_UseCullingMatrixOverride: Optional[bool] = None


@unitypy_define
class ShapeModule:
    angle: float
    enabled: bool
    m_Mesh: PPtr[Mesh]
    placementMode: int
    radius: Union[MultiModeParameter, float]
    type: int
    alignToDirection: Optional[bool] = None
    arc: Optional[Union[MultiModeParameter, float]] = None
    boxThickness: Optional[Vector3f] = None
    boxX: Optional[float] = None
    boxY: Optional[float] = None
    boxZ: Optional[float] = None
    donutRadius: Optional[float] = None
    length: Optional[float] = None
    m_MeshMaterialIndex: Optional[int] = None
    m_MeshNormalOffset: Optional[float] = None
    m_MeshRenderer: Optional[PPtr[MeshRenderer]] = None
    m_MeshScale: Optional[float] = None
    m_MeshSpawn: Optional[MultiModeParameter] = None
    m_Position: Optional[Vector3f] = None
    m_Rotation: Optional[Vector3f] = None
    m_Scale: Optional[Vector3f] = None
    m_SkinnedMeshRenderer: Optional[PPtr[SkinnedMeshRenderer]] = None
    m_Sprite: Optional[PPtr[Sprite]] = None
    m_SpriteRenderer: Optional[PPtr[SpriteRenderer]] = None
    m_Texture: Optional[PPtr[Texture2D]] = None
    m_TextureAlphaAffectsParticles: Optional[bool] = None
    m_TextureBilinearFiltering: Optional[bool] = None
    m_TextureClipChannel: Optional[int] = None
    m_TextureClipThreshold: Optional[float] = None
    m_TextureColorAffectsParticles: Optional[bool] = None
    m_TextureUVChannel: Optional[int] = None
    m_UseMeshColors: Optional[bool] = None
    m_UseMeshMaterialIndex: Optional[bool] = None
    radiusThickness: Optional[float] = None
    randomDirection: Optional[bool] = None
    randomDirectionAmount: Optional[float] = None
    randomPositionAmount: Optional[float] = None
    sphericalDirectionAmount: Optional[float] = None


@unitypy_define
class SizeBySpeedModule:
    curve: MinMaxCurve
    enabled: bool
    range: Vector2f
    separateAxes: Optional[bool] = None
    y: Optional[MinMaxCurve] = None
    z: Optional[MinMaxCurve] = None


@unitypy_define
class SizeModule:
    curve: MinMaxCurve
    enabled: bool
    separateAxes: Optional[bool] = None
    y: Optional[MinMaxCurve] = None
    z: Optional[MinMaxCurve] = None


@unitypy_define
class Skeleton:
    m_AxesArray: List[Axes]
    m_ID: List[int]
    m_Node: List[Node]


@unitypy_define
class SkeletonBone:
    m_Name: str
    m_Position: Vector3f
    m_Rotation: Quaternionf
    m_Scale: Vector3f
    m_ParentName: Optional[str] = None
    m_TransformModified: Optional[bool] = None


@unitypy_define
class SkeletonBoneLimit:
    m_Length: float
    m_Max: Vector3f
    m_Min: Vector3f
    m_Modified: bool
    m_Value: Vector3f
    m_PostQ: Optional[Quaternionf] = None
    m_PreQ: Optional[Quaternionf] = None


@unitypy_define
class SkeletonMask:
    m_Data: List[SkeletonMaskElement]


@unitypy_define
class SkeletonMaskElement:
    m_Weight: float
    m_Index: Optional[int] = None
    m_PathHash: Optional[int] = None


@unitypy_define
class SkeletonPose:
    m_X: List[xform]


@unitypy_define
class SketchUpImportCamera:
    aspectRatio: float
    fov: float
    isPerspective: int
    lookAt: Vector3f
    orthoSize: float
    position: Vector3f
    up: Vector3f
    farPlane: Optional[float] = None
    nearPlane: Optional[float] = None


@unitypy_define
class SketchUpImportData:
    defaultCamera: SketchUpImportCamera
    scenes: List[SketchUpImportScene]


@unitypy_define
class SketchUpImportScene:
    camera: SketchUpImportCamera
    name: str


@unitypy_define
class SnapshotConstant:
    nameHash: int
    transitionIndices: List[int]
    transitionTypes: List[int]
    values: List[float]


@unitypy_define
class SoftJointLimit:
    bounciness: float
    limit: float
    contactDistance: Optional[float] = None
    damper: Optional[float] = None
    spring: Optional[float] = None


@unitypy_define
class SoftJointLimitSpring:
    damper: float
    spring: float


@unitypy_define
class SortingLayerEntry:
    name: str
    uniqueID: int
    userID: Optional[int] = None


@unitypy_define
class SourceAssetIdentifier:
    assembly: str
    name: str
    type: str


@unitypy_define
class SourceLocation:
    m_File: str
    m_Position: int


@unitypy_define
class SourceTextureInformation:
    doesTextureContainAlpha: bool
    height: int
    width: int
    doesTextureContainColor: Optional[bool] = None
    sourceWasHDR: Optional[bool] = None


@unitypy_define
class SpecializationConstantParameter:
    m_Binding: Binding
    m_NameIndex: int


@unitypy_define
class SpeedTreeWind:
    BRANCH_DIRECTIONAL_1: bool
    BRANCH_DIRECTIONAL_2: bool
    BRANCH_DIRECTIONAL_FROND_1: bool
    BRANCH_DIRECTIONAL_FROND_2: bool
    BRANCH_OSC_COMPLEX_1: bool
    BRANCH_OSC_COMPLEX_2: bool
    BRANCH_SIMPLE_1: bool
    BRANCH_SIMPLE_2: bool
    BRANCH_TURBULENCE_1: bool
    BRANCH_TURBULENCE_2: bool
    BRANCH_WHIP_1: bool
    BRANCH_WHIP_2: bool
    BranchWindAnchor0: float
    BranchWindAnchor1: float
    BranchWindAnchor2: float
    FROND_RIPPLE_ADJUST_LIGHTING: bool
    FROND_RIPPLE_ONE_SIDED: bool
    FROND_RIPPLE_TWO_SIDED: bool
    GLOBAL_PRESERVE_SHAPE: bool
    GLOBAL_WIND: bool
    LEAF_OCCLUSION_1: bool
    LEAF_OCCLUSION_2: bool
    LEAF_RIPPLE_COMPUTED_1: bool
    LEAF_RIPPLE_COMPUTED_2: bool
    LEAF_RIPPLE_VERTEX_NORMAL_1: bool
    LEAF_RIPPLE_VERTEX_NORMAL_2: bool
    LEAF_TUMBLE_1: bool
    LEAF_TUMBLE_2: bool
    LEAF_TWITCH_1: bool
    LEAF_TWITCH_2: bool
    ROLLING: bool
    m_fMaxBranchLevel1Length: float
    m_sParams: SParams


@unitypy_define
class SpeedTreeWindConfig8:
    BRANCH_DIRECTIONAL_1: bool
    BRANCH_DIRECTIONAL_2: bool
    BRANCH_DIRECTIONAL_FROND_1: bool
    BRANCH_DIRECTIONAL_FROND_2: bool
    BRANCH_OSC_COMPLEX_1: bool
    BRANCH_OSC_COMPLEX_2: bool
    BRANCH_SIMPLE_1: bool
    BRANCH_SIMPLE_2: bool
    BRANCH_TURBULENCE_1: bool
    BRANCH_TURBULENCE_2: bool
    BRANCH_WHIP_1: bool
    BRANCH_WHIP_2: bool
    BranchLevel1: SBranchWindLevel
    BranchLevel2: SBranchWindLevel
    BranchWindAnchor0: float
    BranchWindAnchor1: float
    BranchWindAnchor2: float
    FROND_RIPPLE_ADJUST_LIGHTING: bool
    FROND_RIPPLE_ONE_SIDED: bool
    FROND_RIPPLE_TWO_SIDED: bool
    GLOBAL_PRESERVE_SHAPE: bool
    GLOBAL_WIND: bool
    LEAF_OCCLUSION_1: bool
    LEAF_OCCLUSION_2: bool
    LEAF_RIPPLE_COMPUTED_1: bool
    LEAF_RIPPLE_COMPUTED_2: bool
    LEAF_RIPPLE_VERTEX_NORMAL_1: bool
    LEAF_RIPPLE_VERTEX_NORMAL_2: bool
    LEAF_TUMBLE_1: bool
    LEAF_TUMBLE_2: bool
    LEAF_TWITCH_1: bool
    LEAF_TWITCH_2: bool
    LeafGroup1: SWindGroup
    LeafGroup2: SWindGroup
    Oscillation0_0: float
    Oscillation0_1: float
    Oscillation0_2: float
    Oscillation0_3: float
    Oscillation0_4: float
    Oscillation0_5: float
    Oscillation0_6: float
    Oscillation0_7: float
    Oscillation0_8: float
    Oscillation0_9: float
    Oscillation1_0: float
    Oscillation1_1: float
    Oscillation1_2: float
    Oscillation1_3: float
    Oscillation1_4: float
    Oscillation1_5: float
    Oscillation1_6: float
    Oscillation1_7: float
    Oscillation1_8: float
    Oscillation1_9: float
    Oscillation2_0: float
    Oscillation2_1: float
    Oscillation2_2: float
    Oscillation2_3: float
    Oscillation2_4: float
    Oscillation2_5: float
    Oscillation2_6: float
    Oscillation2_7: float
    Oscillation2_8: float
    Oscillation2_9: float
    Oscillation3_0: float
    Oscillation3_1: float
    Oscillation3_2: float
    Oscillation3_3: float
    Oscillation3_4: float
    Oscillation3_5: float
    Oscillation3_6: float
    Oscillation3_7: float
    Oscillation3_8: float
    Oscillation3_9: float
    Oscillation4_0: float
    Oscillation4_1: float
    Oscillation4_2: float
    Oscillation4_3: float
    Oscillation4_4: float
    Oscillation4_5: float
    Oscillation4_6: float
    Oscillation4_7: float
    Oscillation4_8: float
    Oscillation4_9: float
    Oscillation5_0: float
    Oscillation5_1: float
    Oscillation5_2: float
    Oscillation5_3: float
    Oscillation5_4: float
    Oscillation5_5: float
    Oscillation5_6: float
    Oscillation5_7: float
    Oscillation5_8: float
    Oscillation5_9: float
    Oscillation6_0: float
    Oscillation6_1: float
    Oscillation6_2: float
    Oscillation6_3: float
    Oscillation6_4: float
    Oscillation6_5: float
    Oscillation6_6: float
    Oscillation6_7: float
    Oscillation6_8: float
    Oscillation6_9: float
    Oscillation7_0: float
    Oscillation7_1: float
    Oscillation7_2: float
    Oscillation7_3: float
    Oscillation7_4: float
    Oscillation7_5: float
    Oscillation7_6: float
    Oscillation7_7: float
    Oscillation7_8: float
    Oscillation7_9: float
    Oscillation8_0: float
    Oscillation8_1: float
    Oscillation8_2: float
    Oscillation8_3: float
    Oscillation8_4: float
    Oscillation8_5: float
    Oscillation8_6: float
    Oscillation8_7: float
    Oscillation8_8: float
    Oscillation8_9: float
    Oscillation9_0: float
    Oscillation9_1: float
    Oscillation9_2: float
    Oscillation9_3: float
    Oscillation9_4: float
    Oscillation9_5: float
    Oscillation9_6: float
    Oscillation9_7: float
    Oscillation9_8: float
    Oscillation9_9: float
    ROLLING: bool
    m_afFrondRippleDistance_0: float
    m_afFrondRippleDistance_1: float
    m_afFrondRippleDistance_2: float
    m_afFrondRippleDistance_3: float
    m_afFrondRippleDistance_4: float
    m_afFrondRippleDistance_5: float
    m_afFrondRippleDistance_6: float
    m_afFrondRippleDistance_7: float
    m_afFrondRippleDistance_8: float
    m_afFrondRippleDistance_9: float
    m_afGlobalDirectionAdherence_0: float
    m_afGlobalDirectionAdherence_1: float
    m_afGlobalDirectionAdherence_2: float
    m_afGlobalDirectionAdherence_3: float
    m_afGlobalDirectionAdherence_4: float
    m_afGlobalDirectionAdherence_5: float
    m_afGlobalDirectionAdherence_6: float
    m_afGlobalDirectionAdherence_7: float
    m_afGlobalDirectionAdherence_8: float
    m_afGlobalDirectionAdherence_9: float
    m_afGlobalDistance_0: float
    m_afGlobalDistance_1: float
    m_afGlobalDistance_2: float
    m_afGlobalDistance_3: float
    m_afGlobalDistance_4: float
    m_afGlobalDistance_5: float
    m_afGlobalDistance_6: float
    m_afGlobalDistance_7: float
    m_afGlobalDistance_8: float
    m_afGlobalDistance_9: float
    m_fAnchorDistanceScale: float
    m_fAnchorOffset: float
    m_fDirectionResponse: float
    m_fFrondRippleLightingScalar: float
    m_fFrondRippleTile: float
    m_fGlobalHeight: float
    m_fGlobalHeightExponent: float
    m_fGustDurationMax: float
    m_fGustDurationMin: float
    m_fGustFallScalar: float
    m_fGustFrequency: float
    m_fGustRiseScalar: float
    m_fGustStrengthMax: float
    m_fGustStrengthMin: float
    m_fMaxBranchLevel1Length: float
    m_fRollingBranchFieldMin: float
    m_fRollingBranchLightingAdjust: float
    m_fRollingBranchVerticalOffset: float
    m_fRollingLeafRippleMin: float
    m_fRollingLeafTumbleMin: float
    m_fRollingNoisePeriod: float
    m_fRollingNoiseSize: float
    m_fRollingNoiseSpeed: float
    m_fRollingNoiseTurbulence: float
    m_fRollingNoiseTwist: float
    m_fStrengthResponse: float


