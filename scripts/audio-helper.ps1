param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("capture", "apply")]
    [string]$Action,

    [string]$EndpointId = "",

    [double]$VolumeScalar = -1
)

$ErrorActionPreference = "Stop"

function Ensure-AudioInterop {
    if ("SwitcherinoAudio.AudioManager" -as [type]) {
        return
    }

    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace SwitcherinoAudio
{
    public enum EDataFlow
    {
        eRender = 0,
        eCapture = 1,
        eAll = 2
    }

    public enum ERole
    {
        eConsole = 0,
        eMultimedia = 1,
        eCommunications = 2
    }

    [Flags]
    public enum CLSCTX
    {
        INPROC_SERVER = 0x1,
        INPROC_HANDLER = 0x2,
        LOCAL_SERVER = 0x4,
        REMOTE_SERVER = 0x10,
        ALL = INPROC_SERVER | INPROC_HANDLER | LOCAL_SERVER | REMOTE_SERVER
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct PROPERTYKEY
    {
        public Guid fmtid;
        public int pid;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct PROPVARIANT
    {
        [FieldOffset(0)]
        public ushort vt;

        [FieldOffset(8)]
        public IntPtr pwszVal;
    }

    [ComImport]
    [Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    public class MMDeviceEnumeratorComObject
    {
    }

    [ComImport]
    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IMMDeviceEnumerator
    {
        int EnumAudioEndpoints(EDataFlow dataFlow, uint dwStateMask, out object ppDevices);
        int GetDefaultAudioEndpoint(EDataFlow dataFlow, ERole role, out IMMDevice ppEndpoint);
        int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string pwstrId, out IMMDevice ppDevice);
        int RegisterEndpointNotificationCallback(IntPtr pClient);
        int UnregisterEndpointNotificationCallback(IntPtr pClient);
    }

    [ComImport]
    [Guid("D666063F-1587-4E43-81F1-B948E807363F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IMMDevice
    {
        int Activate(ref Guid iid, CLSCTX dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
        int OpenPropertyStore(uint stgmAccess, out IPropertyStore ppProperties);
        int GetId([MarshalAs(UnmanagedType.LPWStr)] out string ppstrId);
        int GetState(out uint pdwState);
    }

    [ComImport]
    [Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPropertyStore
    {
        int GetCount(out uint cProps);
        int GetAt(uint iProp, out PROPERTYKEY pkey);
        int GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
        int SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
        int Commit();
    }

    [ComImport]
    [Guid("5CDF2C82-841E-4546-9722-0CF74078229A")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IAudioEndpointVolume
    {
        int RegisterControlChangeNotify(IntPtr pNotify);
        int UnregisterControlChangeNotify(IntPtr pNotify);
        int GetChannelCount(out uint pnChannelCount);
        int SetMasterVolumeLevel(float fLevelDB, Guid pguidEventContext);
        int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);
        int GetMasterVolumeLevel(out float pfLevelDB);
        int GetMasterVolumeLevelScalar(out float pfLevel);
        int SetChannelVolumeLevel(uint nChannel, float fLevelDB, Guid pguidEventContext);
        int SetChannelVolumeLevelScalar(uint nChannel, float fLevel, Guid pguidEventContext);
        int GetChannelVolumeLevel(uint nChannel, out float pfLevelDB);
        int GetChannelVolumeLevelScalar(uint nChannel, out float pfLevel);
        int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, Guid pguidEventContext);
        int GetMute(out bool pbMute);
        int GetVolumeStepInfo(out uint pnStep, out uint pnStepCount);
        int VolumeStepUp(Guid pguidEventContext);
        int VolumeStepDown(Guid pguidEventContext);
        int QueryHardwareSupport(out uint pdwHardwareSupportMask);
        int GetVolumeRange(out float pflVolumeMindB, out float pflVolumeMaxdB, out float pflVolumeIncrementdB);
    }

    [ComImport]
    [Guid("F8679F50-850A-41CF-9C72-430F290290C8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPolicyConfig
    {
        int GetMixFormat();
        int GetDeviceFormat();
        int ResetDeviceFormat();
        int SetDeviceFormat();
        int GetProcessingPeriod();
        int SetProcessingPeriod();
        int GetShareMode();
        int SetShareMode();
        int GetPropertyValue();
        int SetPropertyValue();
        int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string wszDeviceId, ERole role);
        int SetEndpointVisibility([MarshalAs(UnmanagedType.LPWStr)] string wszDeviceId, int bVisible);
    }

    [ComImport]
    [Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")]
    public class PolicyConfigClient
    {
    }

    public class AudioSnapshot
    {
        public string endpoint_id { get; set; }
        public string endpoint_name { get; set; }
        public float volume_scalar { get; set; }
        public bool muted { get; set; }
    }

    public static class AudioManager
    {
        private static PROPERTYKEY PKEY_Device_FriendlyName = new PROPERTYKEY
        {
            fmtid = new Guid("a45c254e-df1c-4efd-8020-67d146a850e0"),
            pid = 14
        };

        [DllImport("ole32.dll")]
        private static extern int PropVariantClear(ref PROPVARIANT pvar);

        public static AudioSnapshot GetDefaultRenderEndpoint()
        {
            IMMDevice device = null;
            IMMDeviceEnumerator enumerator = null;
            IAudioEndpointVolume endpointVolume = null;
            try
            {
                enumerator = GetEnumerator();
                device = enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender, ERole.eMultimedia);
                endpointVolume = GetEndpointVolume(device);
                float volume;
                bool muted;
                Marshal.ThrowExceptionForHR(endpointVolume.GetMasterVolumeLevelScalar(out volume));
                Marshal.ThrowExceptionForHR(endpointVolume.GetMute(out muted));
                return new AudioSnapshot
                {
                    endpoint_id = GetDeviceId(device),
                    endpoint_name = GetDeviceFriendlyName(device),
                    volume_scalar = volume,
                    muted = muted
                };
            }
            finally
            {
                if (endpointVolume != null)
                {
                    Marshal.ReleaseComObject(endpointVolume);
                }
                if (device != null)
                {
                    Marshal.ReleaseComObject(device);
                }
                if (enumerator != null)
                {
                    Marshal.ReleaseComObject(enumerator);
                }
            }
        }

        public static void ApplyRenderEndpoint(string endpointId, float? volumeScalar)
        {
            if (string.IsNullOrWhiteSpace(endpointId))
            {
                throw new ArgumentException("EndpointId is required.", "endpointId");
            }

            var policy = (IPolicyConfig)(new PolicyConfigClient());
            try
            {
                Marshal.ThrowExceptionForHR(policy.SetDefaultEndpoint(endpointId, ERole.eConsole));
                Marshal.ThrowExceptionForHR(policy.SetDefaultEndpoint(endpointId, ERole.eMultimedia));
                Marshal.ThrowExceptionForHR(policy.SetDefaultEndpoint(endpointId, ERole.eCommunications));
            }
            finally
            {
                Marshal.ReleaseComObject(policy);
            }

            if (volumeScalar.HasValue)
            {
                IMMDevice device = null;
                IMMDeviceEnumerator enumerator = null;
                IAudioEndpointVolume endpointVolume = null;
                try
                {
                    enumerator = GetEnumerator();
                    device = enumerator.GetDevice(endpointId);
                    endpointVolume = GetEndpointVolume(device);
                    Marshal.ThrowExceptionForHR(endpointVolume.SetMasterVolumeLevelScalar(volumeScalar.Value, Guid.Empty));
                }
                finally
                {
                    if (endpointVolume != null)
                    {
                        Marshal.ReleaseComObject(endpointVolume);
                    }
                    if (device != null)
                    {
                        Marshal.ReleaseComObject(device);
                    }
                    if (enumerator != null)
                    {
                        Marshal.ReleaseComObject(enumerator);
                    }
                }
            }
        }

        private static IMMDeviceEnumerator GetEnumerator()
        {
            return (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
        }

        private static IMMDevice GetDevice(this IMMDeviceEnumerator enumerator, string endpointId)
        {
            IMMDevice device;
            Marshal.ThrowExceptionForHR(enumerator.GetDevice(endpointId, out device));
            return device;
        }

        private static IMMDevice GetDefaultAudioEndpoint(this IMMDeviceEnumerator enumerator, EDataFlow flow, ERole role)
        {
            IMMDevice device;
            Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(flow, role, out device));
            return device;
        }

        private static string GetDeviceId(IMMDevice device)
        {
            string endpointId;
            Marshal.ThrowExceptionForHR(device.GetId(out endpointId));
            return endpointId;
        }

        private static string GetDeviceFriendlyName(IMMDevice device)
        {
            IPropertyStore store = null;
            PROPVARIANT value = new PROPVARIANT();
            try
            {
                Marshal.ThrowExceptionForHR(device.OpenPropertyStore(0, out store));
                Marshal.ThrowExceptionForHR(store.GetValue(ref PKEY_Device_FriendlyName, out value));
                return Marshal.PtrToStringUni(value.pwszVal) ?? string.Empty;
            }
            finally
            {
                PropVariantClear(ref value);
                if (store != null)
                {
                    Marshal.ReleaseComObject(store);
                }
            }
        }

        private static IAudioEndpointVolume GetEndpointVolume(IMMDevice device)
        {
            object endpointVolume;
            Guid iid = typeof(IAudioEndpointVolume).GUID;
            Marshal.ThrowExceptionForHR(device.Activate(ref iid, CLSCTX.ALL, IntPtr.Zero, out endpointVolume));
            return (IAudioEndpointVolume)endpointVolume;
        }
    }
}
"@
}

Ensure-AudioInterop

if ($Action -eq "capture") {
    try {
        $snapshot = [SwitcherinoAudio.AudioManager]::GetDefaultRenderEndpoint()
        $snapshot | ConvertTo-Json -Compress
    }
    catch {
        Write-Error "Unable to capture the current Windows audio endpoint: $($_.Exception.Message)"
        exit 1
    }
    exit 0
}

try {
    $normalizedVolume = $null
    if ($VolumeScalar -ge 0) {
        $normalizedVolume = [float]$VolumeScalar
    }
    [SwitcherinoAudio.AudioManager]::ApplyRenderEndpoint($EndpointId, $normalizedVolume)
    [pscustomobject]@{
        ok = $true
        endpoint_id = $EndpointId
        volume_scalar = if ($normalizedVolume -ne $null) { $normalizedVolume } else { $null }
    } | ConvertTo-Json -Compress
}
catch {
    Write-Error "Unable to apply the Windows audio endpoint: $($_.Exception.Message)"
    exit 1
}
