# type: ignore
from __future__ import annotations

from ._common import ABC, Object, unitypy_define
from ._part02 import NamedObject
from ._part03 import Texture


@unitypy_define
class SparseTexture(Texture):
    m_ColorSpace: int
    m_Format: int
    m_Height: int
    m_MipCount: int
    m_Name: str
    m_TextureSettings: GLTextureSettings
    m_Width: int
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_IsAlphaChannelOptional: Optional[bool] = None


@unitypy_define
class Texture2D(Texture):
    image_data: bytes
    m_CompleteImageSize: int
    m_Height: int
    m_ImageCount: int
    m_IsReadable: bool
    m_LightmapFormat: int
    m_Name: str
    m_TextureDimension: int
    m_TextureFormat: int
    m_TextureSettings: GLTextureSettings
    m_Width: int
    m_ColorSpace: Optional[int] = None
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_IgnoreMasterTextureLimit: Optional[bool] = None
    m_IgnoreMipmapLimit: Optional[bool] = None
    m_IsAlphaChannelOptional: Optional[bool] = None
    m_IsPreProcessed: Optional[bool] = None
    m_MipCount: Optional[int] = None
    m_MipMap: Optional[bool] = None
    m_MipmapLimitGroupName: Optional[str] = None
    m_MipsStripped: Optional[int] = None
    m_PlatformBlob: Optional[List[int]] = None
    m_ReadAllowed: Optional[bool] = None
    m_StreamData: Optional[StreamingInfo] = None
    m_StreamingMipmaps: Optional[bool] = None
    m_StreamingMipmapsPriority: Optional[int] = None


@unitypy_define
class Cubemap(Texture2D):
    image_data: bytes
    m_CompleteImageSize: int
    m_Height: int
    m_ImageCount: int
    m_IsReadable: bool
    m_LightmapFormat: int
    m_Name: str
    m_TextureDimension: int
    m_TextureFormat: int
    m_TextureSettings: GLTextureSettings
    m_Width: int
    m_ColorSpace: Optional[int] = None
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_IgnoreMasterTextureLimit: Optional[bool] = None
    m_IgnoreMipmapLimit: Optional[bool] = None
    m_IsAlphaChannelOptional: Optional[bool] = None
    m_IsPreProcessed: Optional[bool] = None
    m_MipCount: Optional[int] = None
    m_MipMap: Optional[bool] = None
    m_MipmapLimitGroupName: Optional[str] = None
    m_MipsStripped: Optional[int] = None
    m_PlatformBlob: Optional[List[int]] = None
    m_ReadAllowed: Optional[bool] = None
    m_SourceTextures: Optional[List[PPtr[Texture2D]]] = None
    m_StreamData: Optional[StreamingInfo] = None
    m_StreamingMipmaps: Optional[bool] = None
    m_StreamingMipmapsPriority: Optional[int] = None


@unitypy_define
class Texture2DArray(Texture):
    image_data: bytes
    m_ColorSpace: int
    m_DataSize: int
    m_Depth: int
    m_Format: int
    m_Height: int
    m_IsReadable: bool
    m_MipCount: int
    m_Name: str
    m_TextureSettings: GLTextureSettings
    m_Width: int
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_IgnoreMipmapLimit: Optional[bool] = None
    m_IsAlphaChannelOptional: Optional[bool] = None
    m_MipmapLimitGroupName: Optional[str] = None
    m_MipsStripped: Optional[int] = None
    m_StreamData: Optional[StreamingInfo] = None
    m_UsageMode: Optional[int] = None


@unitypy_define
class Texture3D(Texture):
    image_data: bytes
    m_Height: int
    m_Name: str
    m_TextureSettings: GLTextureSettings
    m_Width: int
    m_ColorSpace: Optional[int] = None
    m_CompleteImageSize: Optional[int] = None
    m_DataSize: Optional[int] = None
    m_Depth: Optional[int] = None
    m_DownscaleFallback: Optional[bool] = None
    m_ForcedFallbackFormat: Optional[int] = None
    m_Format: Optional[int] = None
    m_ImageCount: Optional[int] = None
    m_IsAlphaChannelOptional: Optional[bool] = None
    m_IsReadable: Optional[bool] = None
    m_LightmapFormat: Optional[int] = None
    m_MipCount: Optional[int] = None
    m_MipMap: Optional[bool] = None
    m_ReadAllowed: Optional[bool] = None
    m_StreamData: Optional[StreamingInfo] = None
    m_TextureDimension: Optional[int] = None
    m_TextureFormat: Optional[int] = None
    m_UsageMode: Optional[int] = None


@unitypy_define
class UIAnimationClip(NamedObject):
    m_AnimationClip: PPtr[AnimationClip]
    m_Name: str


@unitypy_define
class VideoClip(NamedObject):
    Height: int
    Width: int
    m_AudioChannelCount: List[int]
    m_AudioLanguage: List[str]
    m_AudioSampleRate: List[int]
    m_ExternalResources: StreamedResource
    m_Format: int
    m_FrameCount: int
    m_FrameRate: float
    m_HasSplitAlpha: bool
    m_Name: str
    m_OriginalPath: str
    m_ProxyHeight: int
    m_ProxyWidth: int
    m_PixelAspecRatioDen: Optional[int] = None
    m_PixelAspecRatioNum: Optional[int] = None
    m_VideoShaders: Optional[List[PPtr[Shader]]] = None
    m_sRGB: Optional[bool] = None


@unitypy_define
class VisualEffectObject(NamedObject, ABC):
    pass


@unitypy_define
class VisualEffectAsset(VisualEffectObject):
    m_Infos: VisualEffectInfo
    m_Name: str
    m_Systems: List[VFXSystemDesc]


@unitypy_define
class VisualEffectSubgraph(VisualEffectObject, ABC):
    pass


@unitypy_define
class VisualEffectSubgraphBlock(VisualEffectSubgraph):
    m_Name: str


@unitypy_define
class VisualEffectSubgraphOperator(VisualEffectSubgraph):
    m_Name: str


@unitypy_define
class VisualEffectResource(NamedObject):
    m_Graph: PPtr[MonoBehaviour]
    m_Infos: Union[VisualEffectInfo, VisualEffectSettings]
    m_Name: str
    m_ShaderSources: Optional[List[VFXShaderSourceDesc]] = None
    m_Systems: Optional[List[VFXEditorSystemDesc]] = None


@unitypy_define
class VulkanDeviceFilterLists(NamedObject):
    m_GfxJobFilterList: List[VulkanGraphicsJobsDeviceFilterData]
    m_Name: str
    m_VulkanAllowFilterList: List[AndroidDeviceFilterData]
    m_VulkanDenyFilterList: List[AndroidDeviceFilterData]


@unitypy_define
class WebGPUDeviceFilterLists(NamedObject):
    m_AllowFilterList: List[WebGPUDeviceFilterData]
    m_DenyFilterList: List[WebGPUDeviceFilterData]
    m_Name: str


@unitypy_define
class EditorExtensionImpl(Object):
    gFlattenedTypeTree: Optional[List[int]] = None
    m_DataTemplate: Optional[PPtr[DataTemplate]] = None
    m_Object: Optional[PPtr[EditorExtension]] = None
    m_OverrideVariable: Optional[bitset] = None
    m_TemplateFather: Optional[PPtr[EditorExtensionImpl]] = None


@unitypy_define
class EditorSettings(Object):
    m_AssetNamingUsesSpace: Optional[bool] = None
    m_AssetPipelineMode: Optional[int] = None
    m_AsyncShaderCompilation: Optional[bool] = None
    m_Bc7TextureCompressor: Optional[int] = None
    m_BlockShaders: Optional[bool] = None
    m_CacheServerDownloadBatchSize: Optional[int] = None
    m_CacheServerEnableAuth: Optional[bool] = None
    m_CacheServerEnableDownload: Optional[bool] = None
    m_CacheServerEnableTls: Optional[bool] = None
    m_CacheServerEnableUpload: Optional[bool] = None
    m_CacheServerEndpoint: Optional[str] = None
    m_CacheServerImportResultCachingEnabled: Optional[bool] = None
    m_CacheServerMode: Optional[int] = None
    m_CacheServerNamespacePrefix: Optional[str] = None
    m_CacheServerValidationMode: Optional[int] = None
    m_CachingShaderPreprocessor: Optional[bool] = None
    m_CollabEditorSettings: Optional[CollabEditorSettings] = None
    m_DefaultBehaviorMode: Optional[int] = None
    m_DisableCookiesInLightmapper: Optional[bool] = None
    m_EnableEditorAsyncCPUTextureLoading: Optional[bool] = None
    m_EnableEnlightenBakedGI: Optional[bool] = None
    m_EnableMSBuildCompilationPipeline: Optional[bool] = None
    m_EnableRoslynAnalyzers: Optional[bool] = None
    m_EnableTextureStreamingInEditMode: Optional[bool] = None
    m_EnableTextureStreamingInPlayMode: Optional[bool] = None
    m_EnterPlayModeOptions: Optional[int] = None
    m_EnterPlayModeOptionsEnabled: Optional[bool] = None
    m_EtcTextureBestCompressor: Optional[int] = None
    m_EtcTextureCompressorBehavior: Optional[int] = None
    m_EtcTextureFastCompressor: Optional[int] = None
    m_EtcTextureNormalCompressor: Optional[int] = None
    m_ExternalVersionControlSupport: Optional[Union[int, str]] = None
    m_ForceAssetUnloadAndGCOnSceneLoad: Optional[bool] = None
    m_GameObjectNamingDigits: Optional[int] = None
    m_GameObjectNamingScheme: Optional[int] = None
    m_HideBuildProfileClassicPlatforms: Optional[bool] = None
    m_InspectorUseIMGUIDefaultInspector: Optional[bool] = None
    m_LineEndingsForNewScripts: Optional[int] = None
    m_PrefabModeAllowAutoSave: Optional[bool] = None
    m_PrefabRegularEnvironment: Optional[PPtr[SceneAsset]] = None
    m_PrefabUIEnvironment: Optional[PPtr[SceneAsset]] = None
    m_ProjectGenerationIncludedExtensions: Optional[str] = None
    m_ProjectGenerationRootNamespace: Optional[str] = None
    m_RecalculateEnvironmentLighting: Optional[bool] = None
    m_ReferencedClipsExactNaming: Optional[bool] = None
    m_RefreshImportMode: Optional[int] = None
    m_SerializationMode: Optional[int] = None
    m_SerializeInlineMappingsOnOneLine: Optional[bool] = None
    m_ShadowmaskStitching: Optional[bool] = None
    m_ShowLightmapResolutionOverlay: Optional[bool] = None
    m_SpritePackerCacheSize: Optional[int] = None
    m_SpritePackerMode: Optional[int] = None
    m_SpritePackerPaddingPower: Optional[int] = None
    m_UnlockBlockShaders: Optional[bool] = None
    m_UseLegacyHierarchy: Optional[bool] = None
    m_UseLegacyProbeSampleCount: Optional[bool] = None
    m_UserGeneratedProjectSuffix: Optional[str] = None
    m_WebSecurityEmulationEnabled: Optional[int] = None
    m_WebSecurityEmulationHostUrl: Optional[str] = None


@unitypy_define
class EditorUserBuildSettings(Object):
    m_ActiveBuildTarget: int
    m_AllowDebugging: bool
    m_ArchitectureFlags: int
    m_BuildLocation: List[str]
    m_ConnectProfiler: bool
    m_Development: bool
    m_InstallInBuildFolder: bool
    m_SelectedAndroidSubtarget: int
    m_SelectedBuildTargetGroup: int
    m_SelectedStandaloneTarget: int
    m_ActiveBuildPlatformGroupName: Optional[str] = None
    m_ActiveBuildProfile: Optional[PPtr[MonoBehaviour]] = None
    m_ActiveBuildTargetGroup: Optional[int] = None
    m_ActivePlatformGuid: Optional[GUID] = None
    m_ActiveProfilePath: Optional[str] = None
    m_ActiveStandaloneBuildSubtarget: Optional[int] = None
    m_AndroidBuildSystem: Optional[int] = None
    m_AndroidBuildType: Optional[int] = None
    m_AndroidCreateSymbols: Optional[int] = None
    m_AndroidCreateSymbolsZip: Optional[bool] = None
    m_AndroidCurrentDeploymentTargetId: Optional[str] = None
    m_AndroidDebugMinification: Optional[int] = None
    m_AndroidDeviceSocketAddress: Optional[str] = None
    m_AndroidReleaseMinification: Optional[int] = None
    m_AndroidUseLegacySdkTools: Optional[bool] = None
    m_BuildAppBundle: Optional[bool] = None
    m_BuildOutputToBuildMetadataMap: Optional[List[Tuple[str, str]]] = None
    m_BuildScriptsOnly: Optional[bool] = None
    m_BuildWithCodeCoverage: Optional[bool] = None
    m_BuildWithDeepProfilingSupport: Optional[bool] = None
    m_CompressFilesInPackage: Optional[bool] = None
    m_CompressWithPsArc: Optional[bool] = None
    m_CreateRomFileForSwitch: Optional[bool] = None
    m_CreateSolutionFileForSwitch: Optional[bool] = None
    m_DatalessPlayer: Optional[bool] = None
    m_EnableDebugPadForSwitch: Optional[bool] = None
    m_EnableHeadlessMode: Optional[bool] = None
    m_EnableHeapInspectorForSwitch: Optional[bool] = None
    m_EnableHostIOForSwitch: Optional[bool] = None
    m_EnableMemoryTrackerForSwitch: Optional[bool] = None
    m_EnableRomCompressionForSwitch: Optional[bool] = None
    m_EnableUnpublishableErrorsForSwitch: Optional[bool] = None
    m_ExplicitArrayBoundsChecks: Optional[bool] = None
    m_ExplicitDivideByZeroChecks: Optional[bool] = None
    m_ExplicitNullChecks: Optional[bool] = None
    m_ExportAsGoogleAndroidProject: Optional[bool] = None
    m_FacebookAccessToken: Optional[str] = None
    m_FacebookCreatePackageForSubmission: Optional[bool] = None
    m_ForceInstallation: Optional[bool] = None
    m_ForceOptimizeScriptCompilation: Optional[bool] = None
    m_GenerateMetroReferenceProjects: Optional[bool] = None
    m_GenerateNintendoSwitchShaderInfo: Optional[bool] = None
    m_GenerateWSAReferenceProjects: Optional[bool] = None
    m_HTCSScriptDebuggingForSwitch: Optional[bool] = None
    m_Il2CppCodeGeneration: Optional[int] = None
    m_MovePackageToDiscOuterEdge: Optional[bool] = None
    m_NVNAftermath: Optional[bool] = None
    m_NVNAftermathLevel: Optional[int] = None
    m_NVNDrawValidation: Optional[bool] = None
    m_NVNDrawValidationHeavy: Optional[bool] = None
    m_NVNDrawValidationLight: Optional[bool] = None
    m_NVNGraphicsDebuggerForSwitch: Optional[bool] = None
    m_NVNShaderDebugging: Optional[bool] = None
    m_NeedSubmissionMaterials: Optional[bool] = None
    m_OverrideMaxTextureSize: Optional[int] = None
    m_OverrideTextureCompression: Optional[int] = None
    m_PS4HardwareTarget: Optional[int] = None
    m_PS5KeepPackageFiles: Optional[bool] = None
    m_PS5WorkspaceName: Optional[str] = None
    m_PathOnRemoteDevice: Optional[str] = None
    m_PlatformSettings: Optional[List[Tuple[str, PlatformSettingsData]]] = None
    m_RedirectWritesToHostMountForSwitch: Optional[bool] = None
    m_RemoteDeviceAddress: Optional[str] = None
    m_RemoteDeviceExports: Optional[str] = None
    m_RemoteDeviceInfo: Optional[bool] = None
    m_RemoteDeviceUsername: Optional[str] = None
    m_RomCompressionConfigForSwitch: Optional[str] = None
    m_RomCompressionLevelForSwitch: Optional[int] = None
    m_RomCompressionTypeForSwitch: Optional[int] = None
    m_SaveADFForSwitch: Optional[bool] = None
    m_SelectedAndroidETC2Fallback: Optional[int] = None
    m_SelectedBlackBerryBuildType: Optional[int] = None
    m_SelectedBlackBerrySubtarget: Optional[int] = None
    m_SelectedBuildPlatformGroupName: Optional[str] = None
    m_SelectedBuildTarget: Optional[int] = None
    m_SelectedCompressionType: Optional[List[Tuple[str, int]]] = None
    m_SelectedDiagnosticSetting: Optional[List[Tuple[str, int]]] = None
    m_SelectedEmbeddedLinuxArchitecture: Optional[int] = None
    m_SelectedFacebookTarget: Optional[int] = None
    m_SelectedIOSBuildType: Optional[int] = None
    m_SelectedMetroBuildAndRunDeployTarget: Optional[int] = None
    m_SelectedMetroBuildType: Optional[int] = None
    m_SelectedMetroSDK: Optional[int] = None
    m_SelectedMetroTarget: Optional[int] = None
    m_SelectedPS3Subtarget: Optional[int] = None
    m_SelectedPS4Subtarget: Optional[int] = None
    m_SelectedPS5CompressionLevel: Optional[int] = None
    m_SelectedPS5CompressionType: Optional[int] = None
    m_SelectedPS5Subtarget: Optional[int] = None
    m_SelectedPSMSubtarget: Optional[int] = None
    m_SelectedPSP2Subtarget: Optional[int] = None
    m_SelectedQNXArchitecture: Optional[int] = None
    m_SelectedQNXOsVersion: Optional[int] = None
    m_SelectedStandaloneBuildSubtarget: Optional[int] = None
    m_SelectedTizenSubtarget: Optional[int] = None
    m_SelectedWSAArchitecture: Optional[str] = None
    m_SelectedWSABuildAndRunDeployTarget: Optional[int] = None
    m_SelectedWSAMinUWPSDK: Optional[str] = None
    m_SelectedWSASDK: Optional[int] = None
    m_SelectedWSASubtarget: Optional[int] = None
    m_SelectedWSAUWPBuildType: Optional[int] = None
    m_SelectedWSAUWPSDK: Optional[str] = None
    m_SelectedWSAUWPVSVersion: Optional[str] = None
    m_SelectedWebGLSubtarget: Optional[int] = None
    m_SelectedWiiDebugLevel: Optional[int] = None
    m_SelectedWiiSubtarget: Optional[int] = None
    m_SelectedWiiUBootMode: Optional[int] = None
    m_SelectedWiiUBuildOutput: Optional[int] = None
    m_SelectedWiiUDebugLevel: Optional[int] = None
    m_SelectedWindowsBuildAndRunDeployTarget: Optional[int] = None
    m_SelectedXboxOneDeployDrive: Optional[int] = None
    m_SelectedXboxOneDeployMethod: Optional[int] = None
    m_SelectedXboxRunMethod: Optional[int] = None
    m_SelectedXboxSubtarget: Optional[int] = None
    m_SymlinkLibraries: Optional[bool] = None
    m_SymlinkSources: Optional[bool] = None
    m_SymlinkTrampoline: Optional[bool] = None
    m_UseLegacyNvnPoolAllocatorForSwitch: Optional[bool] = None
    m_WSADotNetNativeEnabled: Optional[List[bool]] = None
    m_WaitForPlayerConnection: Optional[bool] = None
    m_WaitForSwitchMemoryTrackerOnStartup: Optional[bool] = None
    m_WebGLClientBrowserPath: Optional[str] = None
    m_WebGLClientBrowserType: Optional[int] = None
    m_WebGLClientPlatform: Optional[int] = None
    m_WebGLOptimizationLevel: Optional[int] = None
    m_WebGLUsePreBuiltUnityEngine: Optional[bool] = None
    m_WebPlayerDeployOnline: Optional[bool] = None
    m_WebPlayerNaClSupport: Optional[bool] = None
    m_WebPlayerOfflineDeployment: Optional[bool] = None
    m_WebPlayerStreamed: Optional[bool] = None
    m_WiiUEnableNetAPI: Optional[bool] = None
    m_WindowsDevicePortalAddress: Optional[str] = None
    m_WindowsDevicePortalUsername: Optional[str] = None
    m_WsaHolographicRemoting: Optional[bool] = None
    m_XboxCompressedXex: Optional[bool] = None
    m_XboxOneNetworkSharePath: Optional[str] = None
    m_XboxOneStreamingInstallLaunchChunkRange: Optional[int] = None
    m_XboxOneUsername: Optional[str] = None
    m_macosXcodeBuildConfig: Optional[int] = None


@unitypy_define
class EditorUserSettings(Object):
    m_VCAutomaticAdd: bool
    m_VCDebugCmd: bool
    m_VCDebugCom: bool
    m_VCDebugOut: bool
    m_ArtifactGarbageCollection: Optional[bool] = None
    m_AssetPipelineMode: Optional[int] = None
    m_AssetPipelineMode2: Optional[int] = None
    m_CacheServerMode: Optional[int] = None
    m_CacheServers: Optional[List[str]] = None
    m_CompressAssetsOnImport: Optional[bool] = None
    m_ConfigSettings: Optional[List[Tuple[str, ConfigSetting]]] = None
    m_ConfigValues: Optional[List[Tuple[str, str]]] = None
    m_DesiredImportWorkerCount: Optional[int] = None
    m_IdleImportWorkerShutdownDelay: Optional[int] = None
    m_SemanticMergeMode: Optional[int] = None
    m_StandbyImportWorkerCount: Optional[int] = None
    m_VCAllowAsyncUpdate: Optional[bool] = None
    m_VCAutoRevertUnchangedFiles: Optional[bool] = None
    m_VCHierarchyOverlayIcons: Optional[bool] = None
    m_VCOtherOverlayIcons: Optional[bool] = None
    m_VCOverlayIcons: Optional[bool] = None
    m_VCOverwriteFailedCheckoutAssets: Optional[bool] = None
    m_VCPassword: Optional[str] = None
    m_VCProjectOverlayIcons: Optional[bool] = None
    m_VCScanLocalPackagesOnConnect: Optional[bool] = None
    m_VCServer: Optional[str] = None
    m_VCShowFailedCheckout: Optional[bool] = None
    m_VCUserName: Optional[str] = None
    m_VCWorkspace: Optional[str] = None


@unitypy_define
class EmptyObject(Object):
    pass


@unitypy_define
class GUIDSerializer(Object):
    guidToPath: List[Tuple[GUID, str]]


@unitypy_define
class GameManager(Object, ABC):
    pass


@unitypy_define
class GlobalGameManager(GameManager, ABC):
    pass


@unitypy_define
class AnimationManager(GlobalGameManager):
    pass


@unitypy_define
class AudioManager(GlobalGameManager):
    Default_Speaker_Mode: int
    Doppler_Factor: float
    Rolloff_Scale: float
    m_DSPBufferSize: int
    m_Volume: float
    m_AmbisonicDecoderPlugin: Optional[str] = None
    m_AudioFoundation: Optional[int] = None
    m_DisableAudio: Optional[bool] = None
    m_OutputChannelLayout: Optional[int] = None
    m_OutputSamplingRate: Optional[int] = None
    m_RealVoiceCount: Optional[int] = None
    m_RequestedDSPBufferSize: Optional[int] = None
    m_SampleRate: Optional[int] = None
    m_SpatializerPlugin: Optional[str] = None
    m_SpeedOfSound: Optional[float] = None
    m_VirtualVoiceCount: Optional[int] = None
    m_VirtualizeEffects: Optional[bool] = None


@unitypy_define
class BuildSettings(GlobalGameManager):
    hasAdvancedVersion: bool
    hasPROVersion: bool
    hasPublishingRights: bool
    hasShadows: bool
    isEducationalBuild: bool
    m_Version: str
    buildGUID: Optional[Union[GUID, str]] = None
    buildTags: Optional[List[str]] = None
    enableDynamicBatching: Optional[bool] = None
    enableMultipleDisplays: Optional[bool] = None
    enabledVRDevices: Optional[List[str]] = None
    hasClusterRendering: Optional[bool] = None
    hasLocalLightShadows: Optional[bool] = None
    hasOculusPlugin: Optional[bool] = None
    hasRenderTexture: Optional[bool] = None
    hasSoftShadows: Optional[bool] = None
    isDebugBuild: Optional[bool] = None
    isEmbedded: Optional[bool] = None
    isNoWatermarkBuild: Optional[bool] = None
    isPrototypingBuild: Optional[bool] = None
    isTrial: Optional[bool] = None
    isWsaHolographicRemotingEnabled: Optional[bool] = None
    levels: Optional[List[str]] = None
    m_AuthToken: Optional[str] = None
    m_GraphicsAPIs: Optional[List[int]] = None
    preloadedPlugins: Optional[List[str]] = None
    runtimeClassHashes: Optional[Union[List[Tuple[int, Hash128]], List[Tuple[int, int]]]] = None
    scenes: Optional[List[str]] = None
    scriptHashes: Optional[List[Tuple[Hash128, Hash128]]] = None
    usesOnMouseEvents: Optional[bool] = None


@unitypy_define
class CloudWebServicesManager(GlobalGameManager):
    pass


@unitypy_define
class ClusterInputManager(GlobalGameManager):
    m_Inputs: List[ClusterInput]


@unitypy_define
class CrashReportManager(GlobalGameManager):
    pass


@unitypy_define
class DelayedCallManager(GlobalGameManager):
    pass


@unitypy_define
class GraphicsSettings(GlobalGameManager):
    m_AlwaysIncludedShaders: List[PPtr[Shader]]
    m_AdditionalWarmupCollections: Optional[List[PPtr[GraphicsStateCollection]]] = None
    m_AllowEnlightenSupportForUpgradedProject: Optional[bool] = None
    m_CacheMissCollectionPath: Optional[str] = None
    m_CameraRelativeLightCulling: Optional[bool] = None
    m_CameraRelativeShadowCulling: Optional[bool] = None
    m_CollectionStartupAction: Optional[int] = None
    m_CurrentRenderPipelineGlobalSettings: Optional[PPtr[Object]] = None
    m_CustomRenderPipeline: Optional[PPtr[MonoBehaviour]] = None
    m_DefaultRenderingLayerMask: Optional[int] = None
    m_Deferred: Optional[BuiltinShaderSettings] = None
    m_DeferredReflections: Optional[BuiltinShaderSettings] = None
    m_DepthNormals: Optional[BuiltinShaderSettings] = None
    m_EnableCacheMissTracing: Optional[bool] = None
    m_GraphicsStateCollection: Optional[PPtr[GraphicsStateCollection]] = None
    m_LegacyDeferred: Optional[BuiltinShaderSettings] = None
    m_LensFlare: Optional[BuiltinShaderSettings] = None
    m_LightHalo: Optional[BuiltinShaderSettings] = None
    m_LightProbeOutsideHullStrategy: Optional[int] = None
    m_LightsUseCCT: Optional[bool] = None
    m_LightsUseColorTemperature: Optional[bool] = None
    m_LightsUseLinearIntensity: Optional[bool] = None
    m_LogWhenShaderIsCompiled: Optional[bool] = None
    m_MotionVectors: Optional[BuiltinShaderSettings] = None
    m_PreloadShadersBatchTimeLimit: Optional[int] = None
    m_PreloadedShaders: Optional[List[PPtr[ShaderVariantCollection]]] = None
    m_SRPDefaultSettings: Optional[List[Tuple[str, PPtr[Object]]]] = None
    m_ScreenSpaceShadows: Optional[BuiltinShaderSettings] = None
    m_ShaderDefinesPerShaderCompiler: Optional[List[PlatformShaderDefines]] = None
    m_ShaderSettings: Optional[PlatformShaderSettings] = None
    m_ShaderSettings_Tier1: Optional[PlatformShaderSettings] = None
    m_ShaderSettings_Tier2: Optional[PlatformShaderSettings] = None
    m_ShaderSettings_Tier3: Optional[PlatformShaderSettings] = None
    m_SpritesDefaultMaterial: Optional[PPtr[Material]] = None
    m_TierSettings_Tier1: Optional[TierGraphicsSettings] = None
    m_TierSettings_Tier2: Optional[TierGraphicsSettings] = None
    m_TierSettings_Tier3: Optional[TierGraphicsSettings] = None
    m_TraceSavePath: Optional[str] = None
    m_TraceSendToEditor: Optional[bool] = None
    m_TransparencySortAxis: Optional[Vector3f] = None
    m_TransparencySortMode: Optional[int] = None
    m_VideoShadersIncludeMode: Optional[int] = None
    m_WarmupAsync: Optional[bool] = None
    m_WarmupProgressivelyLimit: Optional[int] = None


@unitypy_define
class InputManager(GlobalGameManager):
    m_Axes: List[InputAxis]
    m_UsePhysicalKeys: Optional[bool] = None


@unitypy_define
class MasterServerInterface(GlobalGameManager):
    pass


@unitypy_define
class MonoManager(GlobalGameManager):
    m_Scripts: List[PPtr[MonoScript]]
    m_AssemblyNames: Optional[List[str]] = None
    m_AssemblyTypes: Optional[List[int]] = None
    m_RuntimeClassHashes: Optional[List[Tuple[int, Hash128]]] = None
    m_ScriptHashes: Optional[List[Tuple[Hash128, Hash128]]] = None


@unitypy_define
class MultiplayerManager(GlobalGameManager):
    m_ActiveMultiplayerRole: Optional[int] = None
    m_ActiveMultiplayerRoles: Optional[int] = None


@unitypy_define
class NavMeshProjectSettings(GlobalGameManager):
    areas: List[NavMeshAreaData]
    m_LastAgentTypeID: Optional[int] = None
    m_SettingNames: Optional[List[str]] = None
    m_Settings: Optional[List[NavMeshBuildSettings]] = None


@unitypy_define
class NetworkManager(GlobalGameManager):
    m_AssetToPrefab: List[Tuple[GUID, PPtr[GameObject]]]
    m_DebugLevel: int
    m_Sendrate: float


@unitypy_define
class NotificationManager(GlobalGameManager):
    pass


@unitypy_define
class PerformanceReportingManager(GlobalGameManager):
    pass


@unitypy_define
class Physics2DSettings(GlobalGameManager):
    m_DefaultMaterial: PPtr[PhysicsMaterial2D]
    m_Gravity: Vector2f
    m_LayerCollisionMatrix: List[int]
    m_PositionIterations: int
    m_VelocityIterations: int
    m_AngularSleepTolerance: Optional[float] = None
    m_AutoSimulation: Optional[bool] = None
    m_AutoSyncTransforms: Optional[bool] = None
    m_BaumgarteScale: Optional[float] = None
    m_BaumgarteTimeOfImpactScale: Optional[float] = None
    m_BounceThreshold: Optional[float] = None
    m_CallbacksOnDisable: Optional[bool] = None
    m_ChangeStopsCallbacks: Optional[bool] = None
    m_ContactThreshold: Optional[float] = None
    m_DefaultContactOffset: Optional[float] = None
    m_DeleteStopsCallbacks: Optional[bool] = None
    m_JobOptions: Optional[PhysicsJobOptions2D] = None
    m_LinearSleepTolerance: Optional[float] = None
    m_MaxAngularCorrection: Optional[float] = None
    m_MaxLinearCorrection: Optional[float] = None
    m_MaxRotationSpeed: Optional[float] = None
    m_MaxSubStepCount: Optional[int] = None
    m_MaxTranslationSpeed: Optional[float] = None
    m_MinPenetrationForPenalty: Optional[float] = None
    m_MinSubStepFPS: Optional[float] = None
    m_PhysicsLowLevelSettings: Optional[PPtr[Object]] = None
    m_QueriesHitTriggers: Optional[bool] = None
    m_QueriesStartInColliders: Optional[bool] = None
    m_RaycastsHitTriggers: Optional[bool] = None
    m_RaycastsStartInColliders: Optional[bool] = None
    m_ReuseCollisionCallbacks: Optional[bool] = None
    m_SimulationLayers: Optional[BitField] = None
    m_SimulationMode: Optional[int] = None
    m_TimeToSleep: Optional[float] = None
    m_UseSubStepContacts: Optional[bool] = None
    m_UseSubStepping: Optional[bool] = None
    m_VelocityThreshold: Optional[float] = None


@unitypy_define
class PhysicsCoreProjectSettings2D(GlobalGameManager):
    m_PhysicsCoreSettings: PPtr[Object]


@unitypy_define
class PhysicsManager(GlobalGameManager):
    m_BounceThreshold: float
    m_DefaultMaterial: Union[PPtr[PhysicMaterial], PPtr[PhysicsMaterial]]
    m_Gravity: Vector3f
    m_LayerCollisionMatrix: List[int]
    m_AutoSimulation: Optional[bool] = None
    m_AutoSyncTransforms: Optional[bool] = None
    m_BroadphaseType: Optional[int] = None
    m_ClothGravity: Optional[Vector3f] = None
    m_ClothInterCollisionDistance: Optional[float] = None
    m_ClothInterCollisionSettingsToggle: Optional[bool] = None
    m_ClothInterCollisionStiffness: Optional[float] = None
    m_ContactPairsMode: Optional[int] = None
    m_ContactsGeneration: Optional[int] = None
    m_CurrentBackendId: Optional[int] = None
    m_DefaultContactOffset: Optional[float] = None
    m_DefaultMaxAngluarSpeed: Optional[float] = None
    m_DefaultMaxAngularSpeed: Optional[float] = None
    m_DefaultMaxDepenetrationVelocity: Optional[float] = None
    m_DefaultSolverIterations: Optional[int] = None
    m_DefaultSolverVelocityIterations: Optional[int] = None
    m_EnableAdaptiveForce: Optional[bool] = None
    m_EnableEnhancedDeterminism: Optional[bool] = None
    m_EnablePCM: Optional[bool] = None
    m_EnableUnifiedHeightmaps: Optional[bool] = None
    m_FastMotionThreshold: Optional[float] = None
    m_FrictionType: Optional[int] = None
    m_GenerateOnTriggerStayEvents: Optional[bool] = None
    m_ImprovedPatchFriction: Optional[bool] = None
    m_IncrementalStaticBroadphase: Optional[bool] = None
    m_InvokeCollisionCallbacks: Optional[bool] = None
    m_LogVerbosity: Optional[int] = None
    m_MaxAngularVelocity: Optional[float] = None
    m_MinPenetrationForPenalty: Optional[float] = None
    m_QueriesHitBackfaces: Optional[bool] = None
    m_QueriesHitTriggers: Optional[bool] = None
    m_RaycastsHitTriggers: Optional[bool] = None
    m_ReleaseSceneBuffers: Optional[bool] = None
    m_ReuseCollisionCallbacks: Optional[bool] = None
    m_SceneBuffersReleaseInterval: Optional[int] = None
    m_ScratchBufferChunkCount: Optional[int] = None
    m_SimulationMode: Optional[int] = None
    m_SleepAngularVelocity: Optional[float] = None
    m_SleepThreshold: Optional[float] = None
    m_SleepVelocity: Optional[float] = None
    m_SolverIterationCount: Optional[int] = None
    m_SolverType: Optional[int] = None
    m_SolverVelocityIterations: Optional[int] = None
    m_ThreadingMode: Optional[int] = None
    m_WorldBounds: Optional[AABB] = None
    m_WorldSubdivisions: Optional[int] = None


@unitypy_define
class PlayerSettings(GlobalGameManager):
    AndroidProfiler: bool
    allowedAutorotateToLandscapeLeft: bool
    allowedAutorotateToLandscapeRight: bool
    allowedAutorotateToPortrait: bool
    allowedAutorotateToPortraitUpsideDown: bool
    companyName: str
    defaultScreenHeight: int
    defaultScreenHeightWeb: int
    defaultScreenOrientation: int
    defaultScreenWidth: int
    defaultScreenWidthWeb: int
    productName: str
    runInBackground: bool
    targetDevice: int
    use32BitDisplayBuffer: bool
    useMacAppStoreValidation: bool
    useOSAutorotation: bool
    usePlayerLog: bool
    AID: Optional[Hash128] = None
    AndroidEnableSustainedPerformanceMode: Optional[bool] = None
    AndroidFilterTouchesWhenObscured: Optional[bool] = None
    AndroidLicensePublicKey: Optional[str] = None
    D3DHDRBitDepth: Optional[int] = None
    Force_IOS_Speakers_When_Recording: Optional[bool] = None
    Override_IPod_Music: Optional[bool] = None
    Prepare_IOS_For_Recording: Optional[bool] = None
    accelerometerFrequency: Optional[int] = None
    activeInputHandler: Optional[int] = None
    adjustIOSFPSUsingThermalState: Optional[bool] = None
    allowFullscreenSwitch: Optional[bool] = None
    allowHDRDisplaySupport: Optional[bool] = None
    allowedHttpConnections: Optional[int] = None
    androidApplicationEntry: Optional[int] = None
    androidAutoRotationBehavior: Optional[int] = None
    androidBlitType: Optional[int] = None
    androidDefaultWindowHeight: Optional[int] = None
    androidDefaultWindowWidth: Optional[int] = None
    androidDisplayOptions: Optional[int] = None
    androidFullscreenMode: Optional[int] = None
    androidMaxAspectRatio: Optional[float] = None
    androidMinAspectRatio: Optional[float] = None
    androidMinimumWindowHeight: Optional[int] = None
    androidMinimumWindowWidth: Optional[int] = None
    androidPredictiveBackSupport: Optional[bool] = None
    androidRenderOutsideSafeArea: Optional[bool] = None
    androidRequestedVisibleInsets: Optional[int] = None
    androidResizableWindow: Optional[bool] = None
    androidResizeableActivity: Optional[bool] = None
    androidShowActivityIndicatorOnLoading: Optional[int] = None
    androidStartInFullscreen: Optional[bool] = None
    androidSupportedAspectRatio: Optional[int] = None
    androidSystemBarsBehavior: Optional[int] = None
    androidUseSwappy: Optional[bool] = None
    androidVulkanAllowFilterList: Optional[List[AndroidDeviceFilterData]] = None
    androidVulkanDenyFilterList: Optional[List[AndroidDeviceFilterData]] = None
    androidVulkanDeviceFilterListAsset: Optional[PPtr[VulkanDeviceFilterLists]] = None
    audioSpatialExperience: Optional[int] = None
    bakeCollisionMeshes: Optional[bool] = None
    bundleIdentifier: Optional[str] = None
    bundleVersion: Optional[str] = None
    callOnDisableOnAssetBundleUnload: Optional[bool] = None
    captureSingleScreen: Optional[bool] = None
    cloudEnabled: Optional[bool] = None
    cloudProjectId: Optional[str] = None
    cpuConfiguration: Optional[List[int]] = None
    cursorHotspot: Optional[Vector2f] = None
    d3d11ForceExclusiveMode: Optional[bool] = None
    d3d11FullscreenMode: Optional[int] = None
    d3d12DeviceFilterListAsset: Optional[PPtr[D3D12DeviceFilterLists]] = None
    d3d9FullscreenMode: Optional[int] = None
    debugUnloadMode: Optional[int] = None
    dedicatedServerOptimizations: Optional[bool] = None
    defaultCursor: Optional[PPtr[Texture2D]] = None
    defaultIsFullScreen: Optional[bool] = None
    defaultIsNativeResolution: Optional[bool] = None
    deferSystemGesturesMode: Optional[int] = None
    disableDepthAndStencilBuffers: Optional[bool] = None
    disableOldInputManagerSupport: Optional[bool] = None
    displayResolutionDialog: Optional[int] = None
    enableDirectStorage: Optional[bool] = None
    enableFrameTimingStats: Optional[bool] = None
    enableGamepadInput: Optional[bool] = None
    enableHWStatistics: Optional[bool] = None
    enableNativePlatformBackendsForNewInputSystem: Optional[bool] = None
    enableNewInputSystem: Optional[bool] = None
    enableOpenGLProfilerGPURecorders: Optional[bool] = None
    forceSRGBBlit: Optional[bool] = None
    forceSingleInstance: Optional[bool] = None
    framebufferDepthMemorylessMode: Optional[int] = None
    fullscreenMode: Optional[int] = None
    gpuSkinning: Optional[bool] = None
    graphicsJobMode: Optional[int] = None
    graphicsJobs: Optional[bool] = None
    hdrBitDepth: Optional[int] = None
    hideHomeButton: Optional[bool] = None
    hmiLoadingImage: Optional[PPtr[Texture2D]] = None
    iPhoneBundleIdentifier: Optional[str] = None
    ignoreAlphaClear: Optional[bool] = None
    insecureHttpOption: Optional[int] = None
    invalidatedPatternTexture: Optional[PPtr[Texture2D]] = None
    iosAllowHTTPDownload: Optional[bool] = None
    iosAppInBackgroundBehavior: Optional[int] = None
    iosShowActivityIndicatorOnLoading: Optional[int] = None
    iosUseCustomAppBackgroundBehavior: Optional[bool] = None
    isWsaHolographicRemotingEnabled: Optional[bool] = None
    legacyClampBlendShapeWeights: Optional[bool] = None
    loadStoreDebugModeEnabled: Optional[bool] = None
    m_ActiveColorSpace: Optional[int] = None
    m_ColorGamuts: Optional[List[int]] = None
    m_HolographicPauseOnTrackingLoss: Optional[bool] = None
    m_HolographicTrackingLossScreen: Optional[PPtr[Texture2D]] = None
    m_MTRendering: Optional[bool] = None
    m_MobileMTRendering: Optional[bool] = None
    m_MobileRenderingPath: Optional[int] = None
    m_RenderingPath: Optional[int] = None
    m_ShowUnitySplashLogo: Optional[bool] = None
    m_ShowUnitySplashScreen: Optional[bool] = None
    m_SplashScreenAnimation: Optional[int] = None
    m_SplashScreenBackgroundAnimationZoom: Optional[float] = None
    m_SplashScreenBackgroundColor: Optional[ColorRGBA] = None
    m_SplashScreenBackgroundLandscape: Optional[PPtr[Texture2D]] = None
    m_SplashScreenBackgroundLandscapeAspect: Optional[float] = None
    m_SplashScreenBackgroundLandscapeUvs: Optional[Rectf] = None
    m_SplashScreenBackgroundPortrait: Optional[PPtr[Texture2D]] = None
    m_SplashScreenBackgroundPortraitAspect: Optional[float] = None
    m_SplashScreenBackgroundPortraitUvs: Optional[Rectf] = None
    m_SplashScreenDrawMode: Optional[int] = None
    m_SplashScreenLogoAnimationZoom: Optional[float] = None
    m_SplashScreenLogoStyle: Optional[int] = None
    m_SplashScreenLogos: Optional[List[SplashScreenLogo]] = None
    m_SplashScreenOverlayOpacity: Optional[float] = None
    m_SplashScreenStyle: Optional[int] = None
    m_SpriteBatchMaxVertexCount: Optional[int] = None
    m_SpriteBatchVertexThreshold: Optional[int] = None
    m_StackTraceTypes: Optional[List[int]] = None
    m_StereoRenderingPath: Optional[int] = None
    m_Stereoscopic3D: Optional[bool] = None
    m_SupportedAspectRatios: Optional[AspectRatios] = None
    m_UnitySplashLogo: Optional[PPtr[Sprite]] = None
    m_UseDX11: Optional[bool] = None
    m_VirtualRealitySplashScreen: Optional[PPtr[Texture2D]] = None
    macAppStoreCategory: Optional[str] = None
    macFullscreenMode: Optional[int] = None
    macRetinaSupport: Optional[bool] = None
    meshDeformation: Optional[int] = None
    metalFramebufferOnly: Optional[bool] = None
    metalUseMetalDisplayLink: Optional[bool] = None
    metroEnableIndependentInputSource: Optional[bool] = None
    metroEnableLowLatencyPresentationAPI: Optional[bool] = None
    metroInputSource: Optional[int] = None
    mipStripping: Optional[bool] = None
    mobileMTRenderingBaked: Optional[bool] = None
    muteOtherAudioSources: Optional[bool] = None
    n3dsDisableStereoscopicView: Optional[bool] = None
    n3dsEnableSharedListOpt: Optional[bool] = None
    n3dsEnableVSync: Optional[bool] = None
    numberOfMipsStripped: Optional[int] = None
    numberOfMipsStrippedPerMipmapLimitGroup: Optional[List[Tuple[str, int]]] = None
    organizationId: Optional[str] = None
    platformRequiresReadableAssets: Optional[bool] = None
    playerDataPath: Optional[str] = None
    playerMinOpenGLESVersion: Optional[int] = None
    preloadedAssets: Optional[List[PPtr[Object]]] = None
    preserveFramebufferAlpha: Optional[bool] = None
    productGUID: Optional[GUID] = None
    projectId: Optional[str] = None
    projectName: Optional[str] = None
    protectGraphicsMemory: Optional[bool] = None
    ps3SplashScreen: Optional[PPtr[Texture2D]] = None
    psp2AcquireBGM: Optional[bool] = None
    psp2PowerMode: Optional[int] = None
    qualitySettingsNames: Optional[List[str]] = None
    resetResolutionOnWindowResize: Optional[bool] = None
    resizableWindow: Optional[bool] = None
    resolutionScalingMode: Optional[int] = None
    singlePassStereoRendering: Optional[bool] = None
    stadiaPresentMode: Optional[int] = None
    stadiaTargetFramerate: Optional[int] = None
    stripPhysics: Optional[bool] = None
    submitAnalytics: Optional[bool] = None
    switchAllowGpuScratchShrinking: Optional[bool] = None
    switchGpuScratchPoolGranularity: Optional[int] = None
    switchGraphicsJobsSyncAfterKick: Optional[bool] = None
    switchMaxWorkerMultiple: Optional[int] = None
    switchNVNDefaultPoolsGranularity: Optional[int] = None
    switchNVNGraphicsFirmwareMemory: Optional[int] = None
    switchNVNMaxPublicSamplerIDCount: Optional[int] = None
    switchNVNMaxPublicTextureIDCount: Optional[int] = None
    switchNVNOtherPoolsGranularity: Optional[int] = None
    switchNVNShaderPoolsGranularity: Optional[int] = None
    switchQueueCommandMemory: Optional[int] = None
    switchQueueComputeMemory: Optional[int] = None
    switchQueueControlMemory: Optional[int] = None
    targetGlesGraphics: Optional[int] = None
    targetIOSGraphics: Optional[int] = None
    targetPixelDensity: Optional[int] = None
    targetPlatform: Optional[int] = None
    targetResolution: Optional[int] = None
    thermalStateCriticalIOSFPS: Optional[int] = None
    thermalStateSeriousIOSFPS: Optional[int] = None
    tizenShowActivityIndicatorOnLoading: Optional[int] = None
    tvOSBundleVersion: Optional[str] = None
    uiUse16BitDepthBuffer: Optional[bool] = None
    unsupportedMSAAFallback: Optional[int] = None
    uploadClearedTextureDataAfterCreationFromScript: Optional[bool] = None
    use24BitDepthBuffer: Optional[bool] = None
    useAlphaInDashboard: Optional[bool] = None
    useFlipModelSwapchain: Optional[bool] = None
    useHDRDisplay: Optional[bool] = None
    useOnDemandResources: Optional[bool] = None
    videoMemoryForVertexBuffers: Optional[int] = None
    virtualRealitySupported: Optional[bool] = None
    virtualTexturingSupportEnabled: Optional[bool] = None
    visibleInBackground: Optional[bool] = None
    visionOSBundleVersion: Optional[str] = None
    vrSettings: Optional[VRSettings] = None
    vulkanEnableCommandBufferRecycling: Optional[bool] = None
    vulkanEnableLateAcquireNextImage: Optional[bool] = None
    vulkanEnablePreTransform: Optional[bool] = None
    vulkanEnableSetSRGBWrite: Optional[bool] = None
    vulkanNumSwapchainBuffers: Optional[int] = None
    vulkanUseSWCommandBuffers: Optional[bool] = None
    webGPUDeviceFilterListAsset: Optional[PPtr[WebGPUDeviceFilterLists]] = None
    webProgressiveAssetLoading: Optional[bool] = None
    wiiHio2Usage: Optional[int] = None
    wiiLoadingScreenBackground: Optional[ColorRGBA] = None
    wiiLoadingScreenFileName: Optional[str] = None
    wiiLoadingScreenPeriod: Optional[int] = None
    wiiLoadingScreenRect: Optional[Rectf] = None
    wiiLoadingScreenRectPlacement: Optional[int] = None
    wiiUAllowScreenCapture: Optional[bool] = None
    wiiUControllerCount: Optional[int] = None
    wiiUGamePadMSAA: Optional[int] = None
    wiiUSupportsBalanceBoard: Optional[bool] = None
    wiiUSupportsClassicController: Optional[bool] = None
    wiiUSupportsMotionPlus: Optional[bool] = None
    wiiUSupportsNunchuk: Optional[bool] = None
    wiiUSupportsProController: Optional[bool] = None
    wiiUTVResolution: Optional[int] = None
    windowsGamepadBackendHint: Optional[int] = None
    wsaTransparentSwapchain: Optional[bool] = None
    xboxEnableAvatar: Optional[bool] = None
    xboxEnableEnableRenderThreadRunsJobs: Optional[bool] = None
    xboxEnableFitness: Optional[bool] = None
    xboxEnableGuest: Optional[bool] = None
    xboxEnableHeadOrientation: Optional[bool] = None
    xboxEnableKinect: Optional[bool] = None
    xboxEnableKinectAutoTracking: Optional[bool] = None
    xboxEnablePIXSampling: Optional[bool] = None
    xboxEnableSpeech: Optional[bool] = None
    xboxOneDisableEsram: Optional[bool] = None
    xboxOneDisableKinectGpuReservation: Optional[bool] = None
    xboxOneEnable7thCore: Optional[bool] = None
    xboxOneEnableTypeOptimization: Optional[bool] = None
    xboxOneLoggingLevel: Optional[int] = None
    xboxOneMonoLoggingLevel: Optional[int] = None
    xboxOnePresentImmediateThreshold: Optional[int] = None
    xboxOneResolution: Optional[int] = None
    xboxOneSResolution: Optional[int] = None
    xboxOneXResolution: Optional[int] = None
    xboxPIXTextureCapture: Optional[bool] = None
    xboxSkinOnGPU: Optional[bool] = None
    xboxSpeechDB: Optional[int] = None


@unitypy_define
class QualitySettings(GlobalGameManager):
    Beautiful: Optional[QualitySetting] = None
    Fantastic: Optional[QualitySetting] = None
    Fast: Optional[QualitySetting] = None
    Fastest: Optional[QualitySetting] = None
    Good: Optional[QualitySetting] = None
    Simple: Optional[QualitySetting] = None
    m_CurrentQuality: Optional[int] = None
    m_DefaultMobileQuality: Optional[int] = None
    m_DefaultStandaloneQuality: Optional[int] = None
    m_DefaultWebPlayerQuality: Optional[int] = None
    m_EditorQuality: Optional[int] = None
    m_QualitySettings: Optional[List[QualitySetting]] = None
    m_StrippedMaximumLODLevel: Optional[int] = None
    m_TextureMipmapLimitGroupNames: Optional[List[str]] = None


@unitypy_define
class ResourceManager(GlobalGameManager):
    m_Container: List[Tuple[str, PPtr[Object]]]
    m_DependentAssets: Optional[List[ResourceManager_Dependency]] = None


@unitypy_define
class RuntimeInitializeOnLoadManager(GlobalGameManager):
    m_AfterAssembliesLoadedMethodExecutionOrders: Optional[List[int]] = None
    m_AfterAssembliesLoadedUnityMethodExecutionOrders: Optional[List[int]] = None
    m_AfterMethodExecutionOrders: Optional[List[int]] = None
    m_AfterUnityMethodExecutionOrders: Optional[List[int]] = None
    m_AssemblyNames: Optional[List[str]] = None
    m_BeforeMethodExecutionOrders: Optional[List[int]] = None
    m_BeforeSplashScreenMethodExecutionOrders: Optional[List[int]] = None
    m_BeforeSplashScreenUnityMethodExecutionOrders: Optional[List[int]] = None
    m_BeforeUnityMethodExecutionOrders: Optional[List[int]] = None
    m_ClassInfos: Optional[List[ClassInfo]] = None
    m_ClassMethodInfos: Optional[List[ClassMethodInfo]] = None
    m_MethodExecutionOrders: Optional[List[int]] = None
    m_NamespaceNames: Optional[List[str]] = None
    m_SubsystemRegistrationMethodExecutionOrders: Optional[List[int]] = None
    m_SubsystemRegistrationUnityMethodExecutionOrders: Optional[List[int]] = None
    m_UnityMethodExecutionOrders: Optional[List[int]] = None


@unitypy_define
class ShaderNameRegistry(GlobalGameManager):
    m_PreloadShaders: bool
    m_Shaders: NameToObjectMap


@unitypy_define
class StreamingManager(GlobalGameManager):
    pass


@unitypy_define
class TagManager(GlobalGameManager):
    tags: List[str]
    Builtin_Layer_0: Optional[str] = None
    Builtin_Layer_1: Optional[str] = None
    Builtin_Layer_2: Optional[str] = None
    Builtin_Layer_3: Optional[str] = None
    Builtin_Layer_4: Optional[str] = None
    Builtin_Layer_5: Optional[str] = None
    Builtin_Layer_6: Optional[str] = None
    Builtin_Layer_7: Optional[str] = None
    User_Layer_10: Optional[str] = None
    User_Layer_11: Optional[str] = None
    User_Layer_12: Optional[str] = None
    User_Layer_13: Optional[str] = None
    User_Layer_14: Optional[str] = None
    User_Layer_15: Optional[str] = None
    User_Layer_16: Optional[str] = None
    User_Layer_17: Optional[str] = None
    User_Layer_18: Optional[str] = None
    User_Layer_19: Optional[str] = None
    User_Layer_20: Optional[str] = None
    User_Layer_21: Optional[str] = None
    User_Layer_22: Optional[str] = None
    User_Layer_23: Optional[str] = None
    User_Layer_24: Optional[str] = None
    User_Layer_25: Optional[str] = None
    User_Layer_26: Optional[str] = None
    User_Layer_27: Optional[str] = None
    User_Layer_28: Optional[str] = None
    User_Layer_29: Optional[str] = None
    User_Layer_30: Optional[str] = None
    User_Layer_31: Optional[str] = None
    User_Layer_8: Optional[str] = None
    User_Layer_9: Optional[str] = None
    layers: Optional[List[str]] = None
    m_RenderingLayers: Optional[List[str]] = None
    m_SortingLayers: Optional[List[SortingLayerEntry]] = None


@unitypy_define
class TimeManager(GlobalGameManager):
    Fixed_Timestep: Union[RationalTime, float]
    Maximum_Allowed_Timestep: float
    m_TimeScale: float
    Maximum_Particle_Timestep: Optional[float] = None


@unitypy_define
class UnityAdsManager(GlobalGameManager):
    pass


@unitypy_define
class UnityAnalyticsManager(GlobalGameManager):
    m_Enabled: Optional[bool] = None
    m_InitializeOnStartup: Optional[bool] = None
    m_TestConfigUrl: Optional[str] = None
    m_TestEventUrl: Optional[str] = None
    m_TestMode: Optional[bool] = None


@unitypy_define
class UnityConnectSettings(GlobalGameManager):
    UnityAnalyticsSettings: UnityAnalyticsSettings
    UnityPurchasingSettings: UnityPurchasingSettings
    CrashReportingSettings: Optional[CrashReportingSettings] = None
    InsightsSettings: Optional[InsightsSettings] = None
    PerformanceReportingSettings: Optional[PerformanceReportingSettings] = None
    UnityAdsSettings: Optional[UnityAdsSettings] = None
    m_ConfigUrl: Optional[str] = None
    m_DashboardUrl: Optional[str] = None
    m_Enabled: Optional[bool] = None
    m_EventOldUrl: Optional[str] = None
    m_EventUrl: Optional[str] = None
    m_TestConfigUrl: Optional[str] = None
    m_TestEventUrl: Optional[str] = None
    m_TestInitMode: Optional[int] = None
    m_TestMode: Optional[bool] = None


@unitypy_define
class VFXManager(GlobalGameManager):
    m_CopyBufferShader: PPtr[ComputeShader]
    m_FixedTimeStep: float
    m_IndirectShader: PPtr[ComputeShader]
    m_MaxDeltaTime: float
    m_RenderPipeSettingsPath: str
    m_SortShader: PPtr[ComputeShader]
    m_BatchEmptyLifetime: Optional[int] = None
    m_CompiledVersion: Optional[int] = None
    m_EmptyShader: Optional[PPtr[Shader]] = None
    m_MaxCapacity: Optional[int] = None
    m_MaxScrubTime: Optional[float] = None
    m_PrefixSumShader: Optional[PPtr[ComputeShader]] = None
    m_RuntimeResources: Optional[PPtr[MonoBehaviour]] = None
    m_RuntimeVersion: Optional[int] = None
    m_StripUpdateShader: Optional[PPtr[ComputeShader]] = None


@unitypy_define
class LevelGameManager(GameManager, ABC):
    pass


@unitypy_define
class HaloManager(LevelGameManager):
    pass


@unitypy_define
class LightmapSettings(LevelGameManager):
    m_Lightmaps: List[LightmapData]
    m_LightmapsMode: int
    m_BakeOnSceneLoad: Optional[int] = None
    m_BakedColorSpace: Optional[int] = None
    m_EnlightenSceneMapping: Optional[EnlightenSceneMapping] = None
    m_GISettings: Optional[GISettings] = None
    m_LightProbes: Optional[PPtr[LightProbes]] = None
    m_LightingSettings: Optional[PPtr[LightingSettings]] = None
    m_RuntimeCPUUsage: Optional[int] = None
    m_ShadowMaskMode: Optional[int] = None
    m_UseDualLightmapsInForward: Optional[bool] = None
    m_UseShadowmask: Optional[bool] = None


@unitypy_define
class NavMeshSettings(LevelGameManager):
    m_NavMesh: Optional[PPtr[NavMesh]] = None
    m_NavMeshData: Optional[PPtr[NavMeshData]] = None


@unitypy_define
class OcclusionCullingSettings(LevelGameManager):
    m_OcclusionCullingData: PPtr[OcclusionCullingData]
    m_Portals: List[PPtr[OcclusionPortal]]
    m_SceneGUID: GUID
    m_StaticRenderers: List[PPtr[Renderer]]


@unitypy_define
class RenderSettings(LevelGameManager):
    m_FlareStrength: float
    m_Fog: bool
    m_FogColor: ColorRGBA
    m_FogDensity: float
    m_FogMode: int
    m_HaloStrength: float
    m_HaloTexture: PPtr[Texture2D]
    m_LinearFogEnd: float
    m_LinearFogStart: float
    m_SkyboxMaterial: PPtr[Material]
    m_SpotCookie: PPtr[Texture2D]
    m_AmbientEquatorColor: Optional[ColorRGBA] = None
    m_AmbientGroundColor: Optional[ColorRGBA] = None
    m_AmbientIntensity: Optional[float] = None
    m_AmbientLight: Optional[ColorRGBA] = None
    m_AmbientMode: Optional[int] = None
    m_AmbientProbe: Optional[SphericalHarmonicsL2] = None
    m_AmbientProbeInGamma: Optional[SphericalHarmonicsL2] = None
    m_AmbientSkyColor: Optional[ColorRGBA] = None
    m_CustomReflection: Optional[Union[PPtr[Cubemap], PPtr[Texture]]] = None
    m_DefaultReflectionMode: Optional[int] = None
    m_DefaultReflectionResolution: Optional[int] = None
    m_FlareFadeSpeed: Optional[float] = None
    m_GeneratedSkyboxReflection: Optional[PPtr[Cubemap]] = None
    m_IndirectSpecularColor: Optional[ColorRGBA] = None
    m_ReflectionBounces: Optional[int] = None
    m_ReflectionIntensity: Optional[float] = None
    m_SubtractiveShadowColor: Optional[ColorRGBA] = None
    m_Sun: Optional[PPtr[Light]] = None
    m_UseRadianceAmbientProbe: Optional[bool] = None


@unitypy_define
class HierarchyState(Object):
    expanded: List[PPtr[Object]]
    selection: List[PPtr[Object]]
    scrollposition_x: Optional[float] = None
    scrollposition_x: Optional[float] = None
    scrollposition_y: Optional[float] = None
    scrollposition_y: Optional[float] = None


@unitypy_define
class InspectorExpandedState(Object):
    m_ExpandedData: List[ExpandedData]


@unitypy_define
class MarshallingTestObject(Object):
    m_Prop: int


@unitypy_define
class MemorySettings(Object):
    pass


