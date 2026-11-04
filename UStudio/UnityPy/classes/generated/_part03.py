# type: ignore
from __future__ import annotations

from ._common import ABC, unitypy_define
from ._part02 import AssetImporter, NamedObject


@unitypy_define
class TrueTypeFontImporter(AssetImporter):
    m_FontNames: List[str]
    m_FontSize: int
    m_ForceTextureCase: int
    m_IncludeFontData: bool
    m_Name: str
    m_AscentCalculationMode: Optional[int] = None
    m_AssetBundleName: Optional[str] = None
    m_AssetBundleVariant: Optional[str] = None
    m_CharacterPadding: Optional[int] = None
    m_CharacterSpacing: Optional[int] = None
    m_CustomCharacters: Optional[str] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FallbackFontReferences: Optional[List[PPtr[Font]]] = None
    m_FileIDToRecycleName: Optional[List[Tuple[int, str]]] = None
    m_FontColor: Optional[ColorRGBA] = None
    m_FontName: Optional[str] = None
    m_FontRenderingMode: Optional[int] = None
    m_NewHashIdentity: Optional[MdFour] = None
    m_OldHashIdentity: Optional[MdFour] = None
    m_Output: Optional[Output] = None
    m_RenderMode: Optional[int] = None
    m_ShouldRoundAdvanceValue: Optional[bool] = None
    m_Style: Optional[int] = None
    m_Use2xBehaviour: Optional[bool] = None
    m_UseLegacyBoundsCalculation: Optional[bool] = None
    m_UsedFileIDs: Optional[List[int]] = None
    m_UserData: Optional[str] = None


@unitypy_define
class VideoClipImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ColorSpace: int
    m_Deinterlace: int
    m_EncodeAlpha: bool
    m_EndFrame: int
    m_FlipHorizontal: bool
    m_FlipVertical: bool
    m_FrameRange: int
    m_Name: str
    m_Output: VideoClipImporterOutput
    m_StartFrame: int
    m_TargetSettings: Union[List[Tuple[int, VideoClipImporterTargetSettings]], List[Tuple[str, VideoClipImporterTargetSettings]]]
    m_UserData: str
    m_AudioImportMode: Optional[int] = None
    m_ExternalObjects: Optional[List[Tuple[SourceAssetIdentifier, PPtr[Object]]]] = None
    m_FrameCount: Optional[int] = None
    m_FrameRate: Optional[float] = None
    m_ImportAudio: Optional[bool] = None
    m_IsColorLinear: Optional[bool] = None
    m_OriginalHeight: Optional[int] = None
    m_OriginalWidth: Optional[int] = None
    m_PixelAspectRatioDenominator: Optional[int] = None
    m_PixelAspectRatioNumerator: Optional[int] = None
    m_Quality: Optional[float] = None
    m_SourceAudioChannelCount: Optional[List[int]] = None
    m_SourceAudioSampleRate: Optional[List[int]] = None
    m_SourceFileSize: Optional[int] = None
    m_SourceHasAlpha: Optional[bool] = None
    m_UseLegacyImporter: Optional[bool] = None
    m_UsedFileIDs: Optional[List[int]] = None


@unitypy_define
class VisualEffectImporter(AssetImporter):
    m_AssetBundleName: str
    m_AssetBundleVariant: str
    m_ExternalObjects: List[Tuple[SourceAssetIdentifier, PPtr[Object]]]
    m_Name: str
    m_UserData: str
    m_Template: Optional[VFXTemplate] = None
    m_UseAsTemplate: Optional[bool] = None
    m_UsedFileIDs: Optional[List[int]] = None


@unitypy_define
class AudioContainerElement(NamedObject):
    m_AudioClip: PPtr[AudioClip]
    m_Enabled: bool
    m_Name: str
    m_Volume: float


@unitypy_define
class AudioMixer(NamedObject):
    m_EnableSuspend: bool
    m_MasterGroup: PPtr[AudioMixerGroup]
    m_MixerConstant: AudioMixerConstant
    m_Name: str
    m_OutputGroup: PPtr[AudioMixerGroup]
    m_Snapshots: List[PPtr[AudioMixerSnapshot]]
    m_StartSnapshot: PPtr[AudioMixerSnapshot]
    m_SuspendThreshold: float
    m_UpdateMode: Optional[int] = None


@unitypy_define
class AudioMixerController(AudioMixer):
    m_EnableSuspend: bool
    m_MasterGroup: PPtr[AudioMixerGroup]
    m_MixerConstant: AudioMixerConstant
    m_Name: str
    m_OutputGroup: PPtr[AudioMixerGroup]
    m_Snapshots: List[PPtr[AudioMixerSnapshot]]
    m_StartSnapshot: PPtr[AudioMixerSnapshot]
    m_SuspendThreshold: float
    m_UpdateMode: Optional[int] = None


@unitypy_define
class AudioMixerEffectController(NamedObject):
    m_Bypass: bool
    m_EffectID: GUID
    m_EffectName: str
    m_EnableWetMix: bool
    m_MixLevel: GUID
    m_Name: str
    m_Parameters: List[Parameter]
    m_SendTarget: PPtr[AudioMixerEffectController]


@unitypy_define
class AudioMixerGroup(NamedObject):
    m_AudioMixer: PPtr[AudioMixer]
    m_Children: List[PPtr[AudioMixerGroup]]
    m_GroupID: GUID
    m_Name: str


@unitypy_define
class AudioMixerGroupController(AudioMixerGroup):
    m_AudioMixer: PPtr[AudioMixer]
    m_Children: List[PPtr[AudioMixerGroup]]
    m_GroupID: GUID
    m_Name: str


@unitypy_define
class AudioMixerSnapshot(NamedObject):
    m_AudioMixer: PPtr[AudioMixer]
    m_Name: str
    m_SnapshotID: GUID


@unitypy_define
class AudioMixerSnapshotController(AudioMixerSnapshot):
    m_AudioMixer: PPtr[AudioMixer]
    m_Name: str
    m_SnapshotID: GUID


@unitypy_define
class AudioResource(NamedObject):
    m_Name: str


@unitypy_define
class AudioRandomContainer(AudioResource):
    m_AutomaticTriggerMode: int
    m_AutomaticTriggerTime: float
    m_AutomaticTriggerTimeRandomizationEnabled: bool
    m_AutomaticTriggerTimeRandomizationRange: Vector2f
    m_AvoidRepeatingLast: int
    m_Elements: List[PPtr[AudioContainerElement]]
    m_LoopCount: int
    m_LoopCountRandomizationEnabled: bool
    m_LoopCountRandomizationRange: Vector2f
    m_LoopMode: int
    m_Name: str
    m_Pitch: float
    m_PitchRandomizationEnabled: bool
    m_PitchRandomizationRange: Vector2f
    m_PlaybackMode: int
    m_TriggerMode: int
    m_Volume: float
    m_VolumeRandomizationEnabled: bool
    m_VolumeRandomizationRange: Vector2f


@unitypy_define
class SampleClip(AudioResource):
    m_Name: str


@unitypy_define
class AudioClip(SampleClip):
    m_Name: str
    m_3D: Optional[bool] = None
    m_Ambisonic: Optional[bool] = None
    m_AudioData: Optional[List[int]] = None
    m_BitsPerSample: Optional[int] = None
    m_Channels: Optional[int] = None
    m_CompressionFormat: Optional[int] = None
    m_Format: Optional[int] = None
    m_Frequency: Optional[int] = None
    m_IsTrackerFormat: Optional[bool] = None
    m_Legacy3D: Optional[bool] = None
    m_Length: Optional[float] = None
    m_LoadInBackground: Optional[bool] = None
    m_LoadType: Optional[int] = None
    m_PreloadAudioData: Optional[bool] = None
    m_Resource: Optional[StreamedResource] = None
    m_Stream: Optional[int] = None
    m_SubsoundIndex: Optional[int] = None
    m_Type: Optional[int] = None
    m_UseHardware: Optional[bool] = None


@unitypy_define
class Avatar(NamedObject):
    m_Avatar: AvatarConstant
    m_AvatarSize: int
    m_Name: str
    m_TOS: List[Tuple[int, str]]
    m_HumanDescription: Optional[HumanDescription] = None


@unitypy_define
class AvatarMask(NamedObject):
    m_Elements: List[TransformMaskElement]
    m_Mask: List[int]
    m_Name: str


@unitypy_define
class AvatarSkeletonMask(NamedObject):
    elements: List[AvatarSkeletonMaskElement]
    m_Name: str


@unitypy_define
class BaseAnimationTrack(NamedObject, ABC):
    pass


@unitypy_define
class NewAnimationTrack(BaseAnimationTrack):
    m_ClassID: int
    m_Curves: List[Channel]
    m_Name: str


@unitypy_define
class BillboardAsset(NamedObject):
    bottom: float
    height: float
    imageTexCoords: List[Vector4f]
    indices: List[int]
    m_Name: str
    material: PPtr[Material]
    vertices: List[Vector2f]
    width: float
    rotated: Optional[List[int]] = None


@unitypy_define
class BlobObject(NamedObject):
    m_BlobData: List[int]
    m_BlobTypeHash: int
    m_Name: str
    m_NestedBlobObjectReferenceOffsets: List[int]
    m_NestedBlobObjectReferences: List[PPtr[BlobObject]]


@unitypy_define
class BlockShaderContainer(NamedObject):
    blob: List[int]
    dependencies: List[PPtr[BlockShaderContainer]]
    generatedPaths: List[str]
    guid: GUID
    m_Name: str
    state: int


@unitypy_define
class BlockShaderErrors(NamedObject):
    errors: List[Error]
    filePath: str
    m_Name: str


@unitypy_define
class BlockShaderSyntaxTree(NamedObject):
    filePath: str
    m_Name: str
    source: str


@unitypy_define
class BuildProfilePlayerSettings(NamedObject):
    AID: Hash128
    AndroidEnableSustainedPerformanceMode: bool
    AndroidFilterTouchesWhenObscured: bool
    AndroidProfiler: bool
    Force_IOS_Speakers_When_Recording: bool
    Prepare_IOS_For_Recording: bool
    accelerometerFrequency: int
    activeInputHandler: int
    adjustIOSFPSUsingThermalState: bool
    allowFullscreenSwitch: bool
    allowHDRDisplaySupport: bool
    allowedAutorotateToLandscapeLeft: bool
    allowedAutorotateToLandscapeRight: bool
    allowedAutorotateToPortrait: bool
    allowedAutorotateToPortraitUpsideDown: bool
    allowedHttpConnections: int
    androidApplicationEntry: int
    androidAutoRotationBehavior: int
    androidBlitType: int
    androidDefaultWindowHeight: int
    androidDefaultWindowWidth: int
    androidDisplayOptions: int
    androidFullscreenMode: int
    androidMaxAspectRatio: float
    androidMinAspectRatio: float
    androidMinimumWindowHeight: int
    androidMinimumWindowWidth: int
    androidPredictiveBackSupport: bool
    androidRenderOutsideSafeArea: bool
    androidRequestedVisibleInsets: int
    androidResizeableActivity: bool
    androidShowActivityIndicatorOnLoading: int
    androidStartInFullscreen: bool
    androidSupportedAspectRatio: int
    androidSystemBarsBehavior: int
    androidUseSwappy: bool
    androidVulkanAllowFilterList: List[AndroidDeviceFilterData]
    androidVulkanDenyFilterList: List[AndroidDeviceFilterData]
    androidVulkanDeviceFilterListAsset: PPtr[VulkanDeviceFilterLists]
    audioSpatialExperience: int
    bakeCollisionMeshes: bool
    bundleVersion: str
    callOnDisableOnAssetBundleUnload: bool
    cloudEnabled: bool
    cloudProjectId: str
    companyName: str
    cursorHotspot: Vector2f
    d3d12DeviceFilterListAsset: PPtr[D3D12DeviceFilterLists]
    dedicatedServerOptimizations: bool
    defaultCursor: PPtr[Texture2D]
    defaultIsNativeResolution: bool
    defaultScreenHeight: int
    defaultScreenHeightWeb: int
    defaultScreenOrientation: int
    defaultScreenWidth: int
    defaultScreenWidthWeb: int
    deferSystemGesturesMode: int
    disableDepthAndStencilBuffers: bool
    enableDirectStorage: bool
    enableFrameTimingStats: bool
    enableOpenGLProfilerGPURecorders: bool
    forceSingleInstance: bool
    framebufferDepthMemorylessMode: int
    fullscreenMode: int
    gpuSkinning: bool
    hdrBitDepth: int
    hideHomeButton: bool
    hmiLoadingImage: PPtr[Texture2D]
    insecureHttpOption: int
    invalidatedPatternTexture: PPtr[Texture2D]
    iosShowActivityIndicatorOnLoading: int
    iosUseCustomAppBackgroundBehavior: bool
    legacyClampBlendShapeWeights: bool
    loadStoreDebugModeEnabled: bool
    m_ActiveColorSpace: int
    m_ColorGamuts: List[int]
    m_MTRendering: bool
    m_Name: str
    m_ShowUnitySplashLogo: bool
    m_ShowUnitySplashScreen: bool
    m_SplashScreenAnimation: int
    m_SplashScreenBackgroundAnimationZoom: float
    m_SplashScreenBackgroundColor: ColorRGBA
    m_SplashScreenBackgroundLandscape: PPtr[Texture2D]
    m_SplashScreenBackgroundLandscapeAspect: float
    m_SplashScreenBackgroundLandscapeUvs: Rectf
    m_SplashScreenBackgroundPortrait: PPtr[Texture2D]
    m_SplashScreenBackgroundPortraitAspect: float
    m_SplashScreenBackgroundPortraitUvs: Rectf
    m_SplashScreenDrawMode: int
    m_SplashScreenLogoAnimationZoom: float
    m_SplashScreenLogoStyle: int
    m_SplashScreenLogos: List[SplashScreenLogo]
    m_SplashScreenOverlayOpacity: float
    m_SpriteBatchMaxVertexCount: int
    m_SpriteBatchVertexThreshold: int
    m_StackTraceTypes: List[int]
    m_StereoRenderingPath: int
    m_UnitySplashLogo: PPtr[Sprite]
    m_VirtualRealitySplashScreen: PPtr[Texture2D]
    macAppStoreCategory: str
    macRetinaSupport: bool
    meshDeformation: int
    metalFramebufferOnly: bool
    metalUseMetalDisplayLink: bool
    metroInputSource: int
    mipStripping: bool
    mobileMTRenderingBaked: bool
    muteOtherAudioSources: bool
    numberOfMipsStripped: int
    numberOfMipsStrippedPerMipmapLimitGroup: List[Tuple[str, int]]
    organizationId: str
    platformRequiresReadableAssets: bool
    playerMinOpenGLESVersion: int
    preloadedAssets: List[PPtr[Object]]
    preserveFramebufferAlpha: bool
    productGUID: GUID
    productName: str
    projectName: str
    qualitySettingsNames: List[str]
    resetResolutionOnWindowResize: bool
    resizableWindow: bool
    resolutionScalingMode: int
    runInBackground: bool
    submitAnalytics: bool
    switchAllowGpuScratchShrinking: bool
    switchGpuScratchPoolGranularity: int
    switchGraphicsJobsSyncAfterKick: bool
    switchMaxWorkerMultiple: int
    switchNVNDefaultPoolsGranularity: int
    switchNVNGraphicsFirmwareMemory: int
    switchNVNMaxPublicSamplerIDCount: int
    switchNVNMaxPublicTextureIDCount: int
    switchNVNOtherPoolsGranularity: int
    switchNVNShaderPoolsGranularity: int
    switchQueueCommandMemory: int
    switchQueueComputeMemory: int
    switchQueueControlMemory: int
    targetDevice: int
    targetPixelDensity: int
    thermalStateCriticalIOSFPS: int
    thermalStateSeriousIOSFPS: int
    tvOSBundleVersion: str
    unsupportedMSAAFallback: int
    use32BitDisplayBuffer: bool
    useFlipModelSwapchain: bool
    useHDRDisplay: bool
    useMacAppStoreValidation: bool
    useOSAutorotation: bool
    useOnDemandResources: bool
    usePlayerLog: bool
    virtualTexturingSupportEnabled: bool
    visibleInBackground: bool
    visionOSBundleVersion: str
    vrSettings: VRSettings
    vulkanEnableCommandBufferRecycling: bool
    vulkanEnableLateAcquireNextImage: bool
    vulkanEnablePreTransform: bool
    vulkanEnableSetSRGBWrite: bool
    vulkanNumSwapchainBuffers: int
    webGPUDeviceFilterListAsset: PPtr[WebGPUDeviceFilterLists]
    windowsGamepadBackendHint: int
    wsaTransparentSwapchain: bool
    xboxEnableAvatar: bool
    xboxEnableFitness: bool
    xboxEnableGuest: bool
    xboxEnableHeadOrientation: bool
    xboxEnableKinect: bool
    xboxEnableKinectAutoTracking: bool
    xboxEnablePIXSampling: bool
    xboxOneDisableEsram: bool
    xboxOneDisableKinectGpuReservation: bool
    xboxOneEnable7thCore: bool
    xboxOneEnableTypeOptimization: bool
    xboxOneLoggingLevel: int
    xboxOneMonoLoggingLevel: int
    xboxOnePresentImmediateThreshold: int
    xboxOneResolution: int
    xboxOneSResolution: int
    xboxOneXResolution: int
    xboxPIXTextureCapture: bool
    xboxSpeechDB: int
    webProgressiveAssetLoading: Optional[bool] = None


@unitypy_define
class BuildReport(NamedObject):
    m_Appendices: List[PPtr[Object]]
    m_BuildSteps: List[BuildStepInfo]
    m_Files: List[BuildReportFile]
    m_Name: str
    m_Summary: BuildSummary
    m_RootAssetPaths: Optional[List[str]] = None


@unitypy_define
class CachedSpriteAtlas(NamedObject):
    frames: List[Tuple[Tuple[GUID, int], SpriteRenderData]]
    textures: List[PPtr[Texture2D]]
    alphaTextures: Optional[List[PPtr[Texture2D]]] = None


@unitypy_define
class CachedSpriteAtlasRuntimeData(NamedObject):
    alphaTextures: List[PPtr[Texture2D]]
    frames: List[Tuple[Tuple[GUID, int], SpriteAtlasData]]
    textures: List[PPtr[Texture2D]]
    currentPackingHash: Optional[Hash128] = None


@unitypy_define
class ComputeShader(NamedObject):
    m_Name: str
    constantBuffers: Optional[List[ComputeShaderCB]] = None
    kernels: Optional[List[ComputeShaderKernel]] = None
    variants: Optional[Union[List[ComputeShaderPlatformVariant], List[ComputeShaderVariant]]] = None


@unitypy_define
class D3D12DeviceFilterLists(NamedObject):
    m_AllowFilterList: List[D3D12DeviceFilterData]
    m_DenyFilterList: List[D3D12DeviceFilterData]
    m_GraphicsJobsFilterList: List[D3D12GraphicsJobsDeviceFilterData]
    m_Name: str


@unitypy_define
class DefaultAsset(NamedObject):
    m_Name: str
    m_ErrorCode: Optional[int] = None
    m_IsWarning: Optional[bool] = None
    m_Message: Optional[str] = None


@unitypy_define
class BrokenPrefabAsset(DefaultAsset):
    m_BrokenParentPrefab: PPtr[BrokenPrefabAsset]
    m_IsPrefabFileValid: bool
    m_IsVariant: bool
    m_IsWarning: bool
    m_Message: str
    m_Name: str
    m_ErrorCode: Optional[int] = None


@unitypy_define
class SceneAsset(DefaultAsset):
    m_Name: str
    m_ErrorCode: Optional[int] = None
    m_IsWarning: Optional[bool] = None
    m_Message: Optional[str] = None


@unitypy_define
class EditorProjectAccess(NamedObject):
    m_Name: str


@unitypy_define
class Flare(NamedObject):
    m_Elements: List[FlareElement]
    m_FlareTexture: PPtr[Texture]
    m_Name: str
    m_TextureLayout: int
    m_UseFog: bool


@unitypy_define
class Font(NamedObject):
    m_Ascent: float
    m_AsciiStartOffset: int
    m_CharacterRects: List[CharacterInfo]
    m_ConvertCase: int
    m_DefaultMaterial: PPtr[Material]
    m_DefaultStyle: int
    m_FontData: List[int]
    m_FontNames: List[str]
    m_FontSize: float
    m_KerningValues: List[Tuple[Tuple[int, int], float]]
    m_LineSpacing: float
    m_Name: str
    m_Texture: PPtr[Texture]
    m_CharacterPadding: Optional[int] = None
    m_CharacterSpacing: Optional[int] = None
    m_Descent: Optional[float] = None
    m_FallbackFonts: Optional[List[PPtr[Font]]] = None
    m_FontCountX: Optional[int] = None
    m_FontCountY: Optional[int] = None
    m_FontRenderingMode: Optional[int] = None
    m_GridFont: Optional[bool] = None
    m_Kerning: Optional[float] = None
    m_PerCharacterKerning: Optional[List[Tuple[int, float]]] = None
    m_PixelScale: Optional[float] = None
    m_ShouldRoundAdvanceValue: Optional[bool] = None
    m_Tracking: Optional[float] = None
    m_UseLegacyBoundsCalculation: Optional[bool] = None


@unitypy_define
class GameObjectRecorder(NamedObject):
    m_Name: str


@unitypy_define
class GraphicsStateCollection(NamedObject):
    m_DeviceRenderer: int
    m_Name: str
    m_QualityLevelName: str
    m_RenderPassInfoMap: List[Tuple[int, RenderPassInfo]]
    m_RenderStateMap: List[Tuple[int, RenderStateInfo]]
    m_RuntimePlatform: int
    m_VariantInfoMap: List[Tuple[Hash128, VariantInfo]]
    m_Version: int
    m_VertexLayoutInfoMap: List[Tuple[int, VertexLayoutInfo]]


@unitypy_define
class HumanTemplate(NamedObject):
    m_BoneTemplate: List[Tuple[str, str]]
    m_Name: str


@unitypy_define
class ImportLog(NamedObject):
    m_Logs: List[ImportLog_ImportLogEntry]
    m_Name: str


@unitypy_define
class LightProbes(NamedObject):
    m_Name: str
    bakedCoefficients: Optional[List[LightmapData]] = None
    bakedPositions: Optional[List[Vector3f]] = None
    hullRays: Optional[List[Vector3f]] = None
    m_BakedCoefficients: Optional[List[SphericalHarmonicsL2]] = None
    m_BakedLightOcclusion: Optional[List[LightProbeOcclusion]] = None
    m_Data: Optional[LightProbeData] = None
    m_HasBeenEdited: Optional[bool] = None
    tetrahedra: Optional[List[Tetrahedron]] = None


@unitypy_define
class LightingDataAsset(NamedObject):
    m_BakedAmbientProbeInLinear: SphericalHarmonicsL2
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
    m_AOTextures: Optional[List[PPtr[Texture2D]]] = None
    m_BakedLightIndices: Optional[List[int]] = None
    m_BakedReflectionProbeCubemapCacheFiles: Optional[List[str]] = None
    m_EnlightenDataVersion: Optional[int] = None
    m_LightBakingOutputs: Optional[List[LightBakingOutput]] = None
    m_LightmapsCacheFiles: Optional[List[str]] = None
    m_LightmapsMode: Optional[int] = None
    m_Scene: Optional[PPtr[SceneAsset]] = None
    m_SceneGUID: Optional[GUID] = None


@unitypy_define
class LightingDataAssetParent(NamedObject):
    m_Name: str


@unitypy_define
class LightingSettings(NamedObject):
    m_AlbedoBoost: float
    m_BounceScale: float
    m_EnableBakedLightmaps: bool
    m_EnableRealtimeLightmaps: bool
    m_Name: str
    m_RealtimeEnvironmentLighting: bool
    m_UsingShadowmask: bool
    m_AO: Optional[bool] = None
    m_AOMaxDistance: Optional[float] = None
    m_BakeBackend: Optional[int] = None
    m_BakeResolution: Optional[float] = None
    m_CompAOExponent: Optional[float] = None
    m_CompAOExponentDirect: Optional[float] = None
    m_ExportTrainingData: Optional[bool] = None
    m_ExtractAO: Optional[bool] = None
    m_FilterMode: Optional[int] = None
    m_FinalGather: Optional[bool] = None
    m_FinalGatherFiltering: Optional[bool] = None
    m_FinalGatherRayCount: Optional[int] = None
    m_ForceUpdates: Optional[bool] = None
    m_ForceWhiteAlbedo: Optional[bool] = None
    m_GIWorkflowMode: Optional[int] = None
    m_IndirectOutputScale: Optional[float] = None
    m_LightmapMaxSize: Optional[int] = None
    m_LightmapParameters: Optional[PPtr[LightmapParameters]] = None
    m_LightmapsBakeMode: Optional[int] = None
    m_MixedBakeMode: Optional[int] = None
    m_PVRBounces: Optional[int] = None
    m_PVRCulling: Optional[bool] = None
    m_PVRDenoiserTypeAO: Optional[int] = None
    m_PVRDenoiserTypeDirect: Optional[int] = None
    m_PVRDenoiserTypeIndirect: Optional[int] = None
    m_PVRDirectSampleCount: Optional[int] = None
    m_PVREnvironmentMIS: Optional[int] = None
    m_PVREnvironmentReferencePointCount: Optional[int] = None
    m_PVREnvironmentSampleCount: Optional[int] = None
    m_PVRFilterTypeAO: Optional[int] = None
    m_PVRFilterTypeDirect: Optional[int] = None
    m_PVRFilterTypeIndirect: Optional[int] = None
    m_PVRFilteringAtrousPositionSigmaAO: Optional[float] = None
    m_PVRFilteringAtrousPositionSigmaDirect: Optional[float] = None
    m_PVRFilteringAtrousPositionSigmaIndirect: Optional[float] = None
    m_PVRFilteringGaussRadiusAO: Optional[int] = None
    m_PVRFilteringGaussRadiusDirect: Optional[int] = None
    m_PVRFilteringGaussRadiusIndirect: Optional[int] = None
    m_PVRFilteringMode: Optional[int] = None
    m_PVRSampleCount: Optional[int] = None
    m_PVRSampling: Optional[int] = None
    m_Padding: Optional[int] = None
    m_RealtimeResolution: Optional[float] = None
    m_TextureCompression: Optional[bool] = None
    m_TrainingDataDestination: Optional[str] = None


@unitypy_define
class LightmapParameters(NamedObject):
    AOAntiAliasingSamples: int
    AOQuality: int
    antiAliasingSamples: int
    backFaceTolerance: float
    bakedLightmapTag: int
    blurRadius: int
    clusterResolution: float
    directLightQuality: int
    edgeStitching: int
    irradianceBudget: int
    irradianceQuality: int
    isTransparent: int
    m_Name: str
    modellingTolerance: float
    resolution: float
    systemTag: int
    limitLightmapCount: Optional[bool] = None
    maxLightmapCount: Optional[int] = None
    pushoff: Optional[float] = None


@unitypy_define
class LocalizationAsset(NamedObject):
    Editor_Asset: bool
    Locale_ISO_Code: str
    String_Table: List[Tuple[str, str]]
    m_Name: str


@unitypy_define
class Material(NamedObject):
    m_Name: str
    m_SavedProperties: UnityPropertySheet
    m_Shader: PPtr[Shader]
    disabledShaderPasses: Optional[List[str]] = None
    m_BuildTextureStacks: Optional[List[BuildTextureStackReference]] = None
    m_CustomRenderQueue: Optional[int] = None
    m_DoubleSidedGI: Optional[bool] = None
    m_EnableInstancingVariants: Optional[bool] = None
    m_InvalidKeywords: Optional[List[str]] = None
    m_LightmapFlags: Optional[int] = None
    m_ShaderKeywords: Optional[Union[List[str], str]] = None
    m_ValidKeywords: Optional[List[str]] = None
    stringTagMap: Optional[List[Tuple[str, str]]] = None


@unitypy_define
class ProceduralMaterial(Material):
    m_Name: str
    m_SavedProperties: UnityPropertySheet
    m_Shader: PPtr[Shader]
    disabledShaderPasses: Optional[List[str]] = None
    m_AnimationUpdateRate: Optional[int] = None
    m_BuildTextureStacks: Optional[List[BuildTextureStackReference]] = None
    m_CacheSize: Optional[int] = None
    m_CustomRenderQueue: Optional[int] = None
    m_DoubleSidedGI: Optional[bool] = None
    m_EnableInstancingVariants: Optional[bool] = None
    m_Flags: Optional[int] = None
    m_GenerateMipmaps: Optional[bool] = None
    m_Hash: Optional[Hash128] = None
    m_Height: Optional[int] = None
    m_Inputs: Optional[List[SubstanceInput]] = None
    m_InvalidKeywords: Optional[List[str]] = None
    m_LightmapFlags: Optional[int] = None
    m_LoadingBehavior: Optional[int] = None
    m_MaximumSize: Optional[int] = None
    m_PrototypeName: Optional[str] = None
    m_ShaderKeywords: Optional[Union[List[str], str]] = None
    m_SubstancePackage: Optional[PPtr[SubstanceArchive]] = None
    m_Textures: Optional[List[PPtr[ProceduralTexture]]] = None
    m_ValidKeywords: Optional[List[str]] = None
    m_Width: Optional[int] = None
    stringTagMap: Optional[List[Tuple[str, str]]] = None


@unitypy_define
class Mesh(NamedObject):
    m_BindPose: List[Matrix4x4f]
    m_CompressedMesh: CompressedMesh
    m_IndexBuffer: List[int]
    m_LocalAABB: AABB
    m_MeshCompression: int
    m_Name: str
    m_SubMeshes: List[SubMesh]
    m_BakedConvexCollisionMesh: Optional[List[int]] = None
    m_BakedTriangleCollisionMesh: Optional[List[int]] = None
    m_BoneNameHashes: Optional[List[int]] = None
    m_BonesAABB: Optional[List[MinMaxAABB]] = None
    m_CollisionTriangles: Optional[List[int]] = None
    m_CollisionVertexCount: Optional[int] = None
    m_Colors: Optional[List[ColorRGBA]] = None
    m_CookingOptions: Optional[int] = None
    m_IndexFormat: Optional[int] = None
    m_IsReadable: Optional[bool] = None
    m_KeepIndices: Optional[bool] = None
    m_KeepVertices: Optional[bool] = None
    m_MeshLodInfo: Optional[MeshLodInfo] = None
    m_MeshMetrics_0_: Optional[float] = None
    m_MeshMetrics_1_: Optional[float] = None
    m_MeshUsageFlags: Optional[int] = None
    m_Normals: Optional[List[Vector3f]] = None
    m_PreBakeConvexCollisionMesh: Optional[bool] = None
    m_PreBakeTriangleCollisionMesh: Optional[bool] = None
    m_RootBoneNameHash: Optional[int] = None
    m_ShapeVertices: Optional[List[MeshBlendShapeVertex]] = None
    m_Shapes: Optional[Union[BlendShapeData, List[MeshBlendShape]]] = None
    m_Skin: Optional[Union[List[BoneInfluence], List[BoneWeights4]]] = None
    m_StreamCompression: Optional[int] = None
    m_StreamData: Optional[StreamingInfo] = None
    m_Tangents: Optional[List[Vector4f]] = None
    m_UV: Optional[List[Vector2f]] = None
    m_UV1: Optional[List[Vector2f]] = None
    m_Use16BitIndices: Optional[int] = None
    m_VariableBoneCountWeights: Optional[VariableBoneCountWeights] = None
    m_VertexData: Optional[VertexData] = None
    m_Vertices: Optional[List[Vector3f]] = None


@unitypy_define
class Motion(NamedObject, ABC):
    pass


@unitypy_define
class AnimationClip(Motion):
    m_Bounds: AABB
    m_Compressed: bool
    m_CompressedRotationCurves: List[CompressedAnimationCurve]
    m_Events: List[AnimationEvent]
    m_FloatCurves: List[FloatCurve]
    m_Name: str
    m_PositionCurves: List[Vector3Curve]
    m_RotationCurves: List[QuaternionCurve]
    m_SampleRate: float
    m_ScaleCurves: List[Vector3Curve]
    m_WrapMode: int
    m_AnimationType: Optional[int] = None
    m_ClipBindingConstant: Optional[AnimationClipBindingConstant] = None
    m_EulerCurves: Optional[List[Vector3Curve]] = None
    m_HasGenericRootTransform: Optional[bool] = None
    m_HasMotionFloatCurves: Optional[bool] = None
    m_Legacy: Optional[bool] = None
    m_MuscleClip: Optional[ClipMuscleConstant] = None
    m_MuscleClipSize: Optional[int] = None
    m_PPtrCurves: Optional[List[PPtrCurve]] = None
    m_UseHighQualityCurve: Optional[bool] = None


@unitypy_define
class PreviewAnimationClip(AnimationClip):
    m_Bounds: AABB
    m_ClipBindingConstant: AnimationClipBindingConstant
    m_Compressed: bool
    m_CompressedRotationCurves: List[CompressedAnimationCurve]
    m_EulerCurves: List[Vector3Curve]
    m_Events: List[AnimationEvent]
    m_FloatCurves: List[FloatCurve]
    m_Legacy: bool
    m_MuscleClip: ClipMuscleConstant
    m_MuscleClipSize: int
    m_Name: str
    m_PPtrCurves: List[PPtrCurve]
    m_PositionCurves: List[Vector3Curve]
    m_RotationCurves: List[QuaternionCurve]
    m_SampleRate: float
    m_ScaleCurves: List[Vector3Curve]
    m_UseHighQualityCurve: bool
    m_WrapMode: int
    m_HasGenericRootTransform: Optional[bool] = None
    m_HasMotionFloatCurves: Optional[bool] = None


@unitypy_define
class BlendTree(Motion):
    m_Childs: Union[List[ChildMotion], List[Child]]
    m_MaxThreshold: float
    m_MinThreshold: float
    m_Name: str
    m_UseAutomaticThresholds: bool
    m_BlendEvent: Optional[str] = None
    m_BlendEventY: Optional[str] = None
    m_BlendParameter: Optional[str] = None
    m_BlendParameterY: Optional[str] = None
    m_BlendType: Optional[int] = None
    m_NormalizedBlendValues: Optional[bool] = None


@unitypy_define
class NavMeshData(NamedObject):
    m_HeightMeshes: List[HeightMeshData]
    m_Heightmaps: List[HeightmapData]
    m_Name: str
    m_NavMeshTiles: List[NavMeshTileData]
    m_OffMeshLinks: List[AutoOffMeshLinkData]
    m_AgentTypeID: Optional[int] = None
    m_NavMeshBuildSettings: Optional[NavMeshBuildSettings] = None
    m_NavMeshParams: Optional[NavMeshParams] = None
    m_Position: Optional[Vector3f] = None
    m_Rotation: Optional[Quaternionf] = None
    m_SourceBounds: Optional[AABB] = None


@unitypy_define
class NavMeshObsolete(NamedObject):
    m_Name: str


@unitypy_define
class OcclusionCullingData(NamedObject):
    m_Name: str
    m_PVSData: List[int]
    m_Scenes: List[OcclusionScene]


@unitypy_define
class PhysicsMaterial(NamedObject):
    m_Name: str
    bounceCombine: Optional[int] = None
    bounciness: Optional[float] = None
    dynamicFriction: Optional[float] = None
    frictionCombine: Optional[int] = None
    m_BounceCombine: Optional[int] = None
    m_Bounciness: Optional[float] = None
    m_DynamicFriction: Optional[float] = None
    m_FrictionCombine: Optional[int] = None
    m_StaticFriction: Optional[float] = None
    staticFriction: Optional[float] = None


@unitypy_define
class PhysicsMaterial2D(NamedObject):
    bounciness: float
    friction: float
    m_Name: str
    m_BounceCombine: Optional[int] = None
    m_FrictionCombine: Optional[int] = None


@unitypy_define
class PreloadData(NamedObject):
    m_Assets: List[PPtr[Object]]
    m_Name: str
    m_Dependencies: Optional[List[str]] = None
    m_ExplicitDataLayout: Optional[bool] = None


@unitypy_define
class Preset(NamedObject):
    m_Name: str
    m_Properties: List[PropertyModification]
    m_TargetType: PresetType
    m_CoupledProperties: Optional[List[PropertyModification]] = None
    m_CoupledType: Optional[PresetType] = None
    m_ExcludedProperties: Optional[List[str]] = None


@unitypy_define
class RayTracingShader(NamedObject):
    m_MaxRecursionDepth: int
    m_Name: str
    variants: Union[List[RayTracingShaderPlatformVariant], List[RayTracingShaderVariant]]
    m_EnableRayPayloadSizeChecks: Optional[bool] = None


@unitypy_define
class RoslynAdditionalFileAsset(NamedObject):
    m_Name: str


@unitypy_define
class RoslynAnalyzerConfigAsset(NamedObject):
    m_Name: str


@unitypy_define
class RuntimeAnimatorController(NamedObject):
    m_AnimationClips: List[PPtr[AnimationClip]]
    m_Controller: ControllerConstant
    m_ControllerSize: int
    m_Name: str
    m_TOS: List[Tuple[int, str]]


@unitypy_define
class AnimatorController(RuntimeAnimatorController):
    m_AnimationClips: List[PPtr[AnimationClip]]
    m_Controller: ControllerConstant
    m_ControllerSize: int
    m_Name: str
    m_TOS: List[Tuple[int, str]]
    m_EvaluateTransitionsOnStart: Optional[bool] = None
    m_MultiThreadedStateMachine: Optional[bool] = None
    m_StateMachineBehaviourVectorDescription: Optional[StateMachineBehaviourVectorDescription] = None
    m_StateMachineBehaviours: Optional[List[PPtr[MonoBehaviour]]] = None


@unitypy_define
class AnimatorOverrideController(RuntimeAnimatorController):
    m_Clips: List[AnimationClipOverride]
    m_Controller: PPtr[RuntimeAnimatorController]
    m_Name: str


@unitypy_define
class Shader(NamedObject):
    m_Name: str
    compressedBlob: Optional[List[int]] = None
    compressedLengths: Optional[Union[List[List[int]], List[int]]] = None
    decompressedLengths: Optional[Union[List[List[int]], List[int]]] = None
    decompressedSize: Optional[int] = None
    m_AssetGUID: Optional[GUID] = None
    m_AssetLocalIdentifierInFile: Optional[int] = None
    m_Dependencies: Optional[List[PPtr[Shader]]] = None
    m_NonModifiableTextures: Optional[List[Tuple[str, PPtr[Texture]]]] = None
    m_ParsedForm: Optional[SerializedShader] = None
    m_PathName: Optional[str] = None
    m_Script: Optional[str] = None
    m_ShaderIsBaked: Optional[bool] = None
    m_SubProgramBlob: Optional[List[int]] = None
    offsets: Optional[Union[List[List[int]], List[int]]] = None
    platforms: Optional[List[int]] = None
    stageCounts: Optional[List[int]] = None


@unitypy_define
class ShaderVariantCollection(NamedObject):
    m_Name: str
    m_Shaders: List[Tuple[PPtr[Shader], ShaderInfo]]


@unitypy_define
class SpeedTreeWindAsset(NamedObject):
    m_Name: str
    m_Config8: Optional[SpeedTreeWindConfig8] = None
    m_Config9: Optional[SpeedTreeWindConfig9] = None
    m_Wind: Optional[SpeedTreeWind] = None
    m_eVersion: Optional[int] = None


@unitypy_define
class Sprite(NamedObject):
    m_Extrude: int
    m_Name: str
    m_Offset: Vector2f
    m_PixelsToUnits: float
    m_RD: SpriteRenderData
    m_Rect: Rectf
    m_AtlasTags: Optional[List[str]] = None
    m_Bones: Optional[List[SpriteBone]] = None
    m_Border: Optional[Vector4f] = None
    m_IsPolygon: Optional[bool] = None
    m_PhysicsShape: Optional[List[List[Vector2f]]] = None
    m_Pivot: Optional[Vector2f] = None
    m_RenderDataKey: Optional[Tuple[GUID, int]] = None
    m_ScriptableObjects: Optional[List[PPtr[MonoBehaviour]]] = None
    m_SpriteAtlas: Optional[PPtr[SpriteAtlas]] = None


@unitypy_define
class SpriteAtlas(NamedObject):
    m_IsVariant: bool
    m_Name: str
    m_RenderDataMap: List[Tuple[Tuple[GUID, int], SpriteAtlasData]]
    m_Tag: str
    m_Guid: Optional[GUID] = None
    m_PackedSpriteNamesToIndex: Optional[List[str]] = None
    m_PackedSprites: Optional[List[PPtr[Sprite]]] = None


@unitypy_define
class SpriteAtlasAsset(NamedObject):
    m_ImporterData: Union[SpriteAtlasAssetData, SpriteAtlasEditorData]
    m_IsVariant: bool
    m_MasterAtlas: PPtr[SpriteAtlas]
    m_Name: str
    m_ScriptablePacker: Optional[PPtr[Object]] = None


@unitypy_define
class SubstanceArchive(NamedObject):
    m_Name: str
    m_PackageData: Optional[List[int]] = None


@unitypy_define
class TerrainData(NamedObject):
    m_DetailDatabase: DetailDatabase
    m_Heightmap: Heightmap
    m_Name: str
    m_SplatDatabase: SplatDatabase
    m_PreloadShaders: Optional[List[PPtr[Shader]]] = None


@unitypy_define
class TerrainLayer(NamedObject):
    m_DiffuseRemapMax: Vector4f
    m_DiffuseRemapMin: Vector4f
    m_DiffuseTexture: PPtr[Texture2D]
    m_MaskMapRemapMax: Vector4f
    m_MaskMapRemapMin: Vector4f
    m_MaskMapTexture: PPtr[Texture2D]
    m_Metallic: float
    m_Name: str
    m_NormalMapTexture: PPtr[Texture2D]
    m_NormalScale: float
    m_Smoothness: float
    m_Specular: ColorRGBA
    m_TileOffset: Vector2f
    m_TileSize: Vector2f
    m_SmoothnessSource: Optional[int] = None


@unitypy_define
class TextAsset(NamedObject):
    m_Name: str
    m_Script: str
    m_PathName: Optional[str] = None


@unitypy_define
class AssemblyDefinitionAsset(TextAsset):
    m_Name: str
    m_Script: str


@unitypy_define
class AssemblyDefinitionReferenceAsset(TextAsset):
    m_Name: str
    m_Script: str


@unitypy_define
class MonoScript(TextAsset):
    m_AssemblyName: str
    m_ClassName: str
    m_ExecutionOrder: int
    m_Name: str
    m_Namespace: str
    m_PropertiesHash: Union[Hash128, int]
    m_IsEditorScript: Optional[bool] = None


@unitypy_define
class PackageManifest(TextAsset):
    m_Name: str
    m_Script: str


@unitypy_define
class RuleSetFileAsset(TextAsset):
    m_Name: str
    m_Script: str


@unitypy_define
class ShaderInclude(TextAsset):
    m_Name: str
    m_Script: Optional[str] = None


@unitypy_define
class Texture(NamedObject, ABC):
    pass


@unitypy_define
class BaseVideoTexture(Texture, ABC):
    pass


@unitypy_define
class WebCamTexture(BaseVideoTexture):
    m_Name: str
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_IsAlphaChannelOptional: Optional[bool] = None


@unitypy_define
class CubemapArray(Texture):
    image_data: bytes
    m_ColorSpace: int
    m_CubemapCount: int
    m_DataSize: int
    m_Format: int
    m_IsReadable: bool
    m_MipCount: int
    m_Name: str
    m_TextureSettings: GLTextureSettings
    m_Width: int
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_IsAlphaChannelOptional: Optional[bool] = None
    m_StreamData: Optional[StreamingInfo] = None
    m_UsageMode: Optional[int] = None


@unitypy_define
class LowerResBlitTexture(Texture):
    m_Name: str
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_IsAlphaChannelOptional: Optional[bool] = None


@unitypy_define
class MovieTexture(Texture):
    m_Name: str
    m_AudioClip: Optional[PPtr[AudioClip]] = None
    m_ColorSpace: Optional[int] = None
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_IsAlphaChannelOptional: Optional[bool] = None
    m_Loop: Optional[bool] = None
    m_MovieData: Optional[List[int]] = None


@unitypy_define
class ProceduralTexture(Texture):
    m_Name: str
    AlphaSource: Optional[int] = None
    AlphaSourceIsGrayscale: Optional[bool] = None
    Format: Optional[int] = None
    Type: Optional[int] = None
    m_AlphaSourceIsInverted: Optional[bool] = None
    m_AlphaSourceUID: Optional[int] = None
    m_BakedData: Optional[List[int]] = None
    m_BakedParameters: Optional[TextureParameters] = None
    m_ColorSpace: Optional[int] = None
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_IsAlphaChannelOptional: Optional[bool] = None
    m_LightmapFormat: Optional[int] = None
    m_Mipmaps: Optional[int] = None
    m_SubstanceMaterial: Optional[PPtr[ProceduralMaterial]] = None
    m_SubstanceTextureUID: Optional[int] = None
    m_TextureParameters: Optional[TextureParameters] = None
    m_TextureSettings: Optional[GLTextureSettings] = None


@unitypy_define
class RenderTexture(Texture):
    m_ColorFormat: int
    m_Height: int
    m_MipMap: bool
    m_Name: str
    m_TextureSettings: GLTextureSettings
    m_Width: int
    m_AntiAliasing: Optional[int] = None
    m_BindMS: Optional[bool] = None
    m_DepthFormat: Optional[int] = None
    m_DepthStencilFormat: Optional[int] = None
    m_Dimension: Optional[int] = None
    m_DownscaleFallback: Optional[bool] = None
    m_EnableCompatibleFormat: Optional[bool] = None
    m_EnableRandomWrite: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_GenerateMips: Optional[bool] = None
    m_IsAlphaChannelOptional: Optional[bool] = None
    m_IsCubemap: Optional[bool] = None
    m_IsPowerOfTwo: Optional[bool] = None
    m_MipCount: Optional[int] = None
    m_SRGB: Optional[bool] = None
    m_ShadowSamplingMode: Optional[int] = None
    m_UseDynamicScale: Optional[bool] = None
    m_UseDynamicScaleExplicit: Optional[bool] = None
    m_VolumeDepth: Optional[int] = None


@unitypy_define
class CustomRenderTexture(RenderTexture):
    m_AntiAliasing: int
    m_ColorFormat: int
    m_CubemapFaceMask: int
    m_CurrentUpdateZoneSpace: int
    m_Dimension: int
    m_DoubleBuffered: bool
    m_GenerateMips: bool
    m_Height: int
    m_InitColor: ColorRGBA
    m_InitMaterial: PPtr[Material]
    m_InitTexture: PPtr[Texture]
    m_InitializationMode: int
    m_Material: PPtr[Material]
    m_MipMap: bool
    m_Name: str
    m_SRGB: bool
    m_ShaderPass: int
    m_TextureSettings: GLTextureSettings
    m_UpdateMode: int
    m_UpdatePeriod: float
    m_UpdateZoneSpace: int
    m_UpdateZones: List[UpdateZoneInfo]
    m_VolumeDepth: int
    m_Width: int
    m_WrapUpdateZones: bool
    m_BindMS: Optional[bool] = None
    m_DepthFormat: Optional[int] = None
    m_DepthStencilFormat: Optional[int] = None
    m_DownscaleFallback: Optional[bool] = None
    m_EnableCompatibleFormat: Optional[bool] = None
    m_EnableRandomWrite: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_InitSource: Optional[int] = None
    m_IsAlphaChannelOptional: Optional[bool] = None
    m_MipCount: Optional[int] = None
    m_ShadowSamplingMode: Optional[int] = None
    m_UseDynamicScale: Optional[bool] = None
    m_UseDynamicScaleExplicit: Optional[bool] = None


