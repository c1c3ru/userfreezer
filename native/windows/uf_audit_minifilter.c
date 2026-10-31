/*
 * UserFreezer native Windows minifilter - LABORATORY AUDIT PROTOTYPE ONLY.
 *
 * NO redirection, NO data modification, NO denial, NO deployment artifacts.
 * This is not a freezing engine, and must not be packaged as such.
 * An assigned filter-manager altitude, signing and a real Win7/10/11 WDK
 * build are required before even a disposable-VM driver installation.
 *
 * This file is intentionally NOT referenced from production builds.
 */
#include <fltKernel.h>

#define UF_REGISTRY_MAX 256
#define UF_VOLUME_MAX 128
#define UF_LOG_INTERVAL 256

static PFLT_FILTER gFilter = NULL;
static BOOLEAN gLabConfigured = FALSE;
static WCHAR gLabVolumeName[UF_VOLUME_MAX] = { 0 };
static UNICODE_STRING gLabVolume;
static volatile LONG gCreates = 0;
static volatile LONG gWrites = 0;
static volatile LONG gSetInfo = 0;

static
NTSTATUS
UfQueryValue(
    _In_ HANDLE Key,
    _In_ PCWSTR Name,
    _Out_writes_bytes_(BufferSize) PVOID Buffer,
    _In_ ULONG BufferSize,
    _Out_ PKEY_VALUE_PARTIAL_INFORMATION *Result
    )
{
    ULONG needed = 0;
    UNICODE_STRING valueName;
    NTSTATUS status;

    RtlInitUnicodeString(&valueName, Name);
    status = ZwQueryValueKey(
        Key, &valueName, KeyValuePartialInformation, Buffer,
        BufferSize, &needed);
    if (!NT_SUCCESS(status)) {
        return status;
    }
    if (needed > BufferSize ||
        ((PKEY_VALUE_PARTIAL_INFORMATION)Buffer)->DataLength >
        BufferSize - FIELD_OFFSET(KEY_VALUE_PARTIAL_INFORMATION, Data)) {
        return STATUS_INVALID_PARAMETER;
    }
    *Result = (PKEY_VALUE_PARTIAL_INFORMATION)Buffer;
    return STATUS_SUCCESS;
}

static
BOOLEAN
UfValidLabVolumeName(_In_ PCWSTR Volume)
{
    /* A native NTFS volume device (NOT drive letter, profile or system root).
       Avoid prefix collisions, UNC, globalroot and shadow copies. */
    static const WCHAR prefix[] = L"\\Device\\HarddiskVolume";
    ULONG i = 0;
    ULONG length = 0;

    while (Volume[length] != L'\0' && length < UF_VOLUME_MAX) {
        ++length;
    }
    if (length == UF_VOLUME_MAX ||
        length <= (RTL_NUMBER_OF(prefix) - 1)) {
        return FALSE;
    }
    for (i = 0; i < RTL_NUMBER_OF(prefix) - 1; ++i) {
        if (Volume[i] != prefix[i]) {
            return FALSE;
        }
    }
    /* Only numeric HarddiskVolume identifiers are accepted. */
    for (; i < length; ++i) {
        if (Volume[i] < L'0' || Volume[i] > L'9') {
            return FALSE;
        }
    }
    return TRUE;
}

static
VOID
UfLoadLabConfig(_In_ PUNICODE_STRING RegistryPath)
{
    HANDLE service = NULL, parameters = NULL;
    OBJECT_ATTRIBUTES attrs;
    UNICODE_STRING parametersName;
    NTSTATUS status;
    ULONG enabled = 0;
    union {
        KEY_VALUE_PARTIAL_INFORMATION info;
        UCHAR bytes[UF_REGISTRY_MAX];
        ULONGLONG alignment;
    } value;
    PKEY_VALUE_PARTIAL_INFORMATION part = NULL;

    /* Fail closed: no explicit opt-in + exact NT volume = no attach. */
    gLabConfigured = FALSE;
    InitializeObjectAttributes(
        &attrs, RegistryPath, OBJ_KERNEL_HANDLE | OBJ_CASE_INSENSITIVE,
        NULL, NULL);
    status = ZwOpenKey(&service, KEY_READ, &attrs);
    if (!NT_SUCCESS(status)) {
        return;
    }

    RtlInitUnicodeString(&parametersName, L"Parameters");
    InitializeObjectAttributes(
        &attrs, &parametersName,
        OBJ_KERNEL_HANDLE | OBJ_CASE_INSENSITIVE, service, NULL);
    status = ZwOpenKey(&parameters, KEY_READ, &attrs);
    ZwClose(service);
    if (!NT_SUCCESS(status)) {
        return;
    }

    status = UfQueryValue(
        parameters, L"LabAuditEnabled", value.bytes, sizeof(value), &part);
    if (NT_SUCCESS(status) && part->Type == REG_DWORD &&
        part->DataLength == sizeof(ULONG)) {
        RtlCopyMemory(&enabled, part->Data, sizeof(enabled));
    }
    if (enabled != 1) {
        ZwClose(parameters);
        return;
    }
    RtlZeroMemory(&value, sizeof(value));
    status = UfQueryValue(
        parameters, L"LabVolumeNtName", value.bytes, sizeof(value), &part);
    if (NT_SUCCESS(status) &&
        part->Type == REG_SZ &&
        part->DataLength >= sizeof(WCHAR) * 2 &&
        part->DataLength <= sizeof(gLabVolumeName) &&
        part->DataLength % sizeof(WCHAR) == 0 &&
        ((PWCHAR)part->Data)[part->DataLength / sizeof(WCHAR) - 1] == L'\0') {
        RtlZeroMemory(gLabVolumeName, sizeof(gLabVolumeName));
        RtlCopyMemory(gLabVolumeName, part->Data, part->DataLength);
        if (UfValidLabVolumeName(gLabVolumeName)) {
            RtlInitUnicodeString(&gLabVolume, gLabVolumeName);
            gLabConfigured = TRUE;
        }
    }
    ZwClose(parameters);
}

static
NTSTATUS
UfInstanceSetup(
    _In_ PCFLT_RELATED_OBJECTS FltObjects,
    _In_ FLT_INSTANCE_SETUP_FLAGS Flags,
    _In_ DEVICE_TYPE VolumeDeviceType,
    _In_ FLT_FILESYSTEM_TYPE VolumeFilesystemType
    )
{
    NTSTATUS status;
    WCHAR nameBuffer[UF_VOLUME_MAX];
    UNICODE_STRING name;

    UNREFERENCED_PARAMETER(Flags);
    UNREFERENCED_PARAMETER(VolumeDeviceType);

    if (!gLabConfigured || VolumeFilesystemType != FLT_FSTYPE_NTFS) {
        return STATUS_FLT_DO_NOT_ATTACH;
    }

    RtlZeroMemory(nameBuffer, sizeof(nameBuffer));
    name.Buffer = nameBuffer;
    name.Length = 0;
    name.MaximumLength = sizeof(nameBuffer);
    status = FltGetVolumeName(FltObjects->Volume, &name, NULL);
    if (!NT_SUCCESS(status) ||
        !RtlEqualUnicodeString(&name, &gLabVolume, TRUE)) {
        return STATUS_FLT_DO_NOT_ATTACH;
    }

    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID, DPFLTR_INFO_LEVEL,
        "UserFreezerAudit: attached to explicitly authorized NTFS lab volume\n");
    return STATUS_SUCCESS;
}

static
FLT_PREOP_CALLBACK_STATUS
UfObserveOnly(
    _Inout_ PFLT_CALLBACK_DATA Data,
    _In_ PCFLT_RELATED_OBJECTS FltObjects,
    _Flt_CompletionContext_Outptr_ PVOID *CompletionContext
    )
{
    LONG total = 0;
    UCHAR major = Data->Iopb->MajorFunction;

    UNREFERENCED_PARAMETER(FltObjects);
    *CompletionContext = NULL;

    /* Count attempted operations; successful completion NOT observed. */
    switch (major) {
    case IRP_MJ_CREATE:
        total = InterlockedIncrement(&gCreates);
        break;
    case IRP_MJ_WRITE:
        total = InterlockedIncrement(&gWrites);
        break;
    case IRP_MJ_SET_INFORMATION:
        total = InterlockedIncrement(&gSetInfo);
        break;
    default:
        break;
    }
    /* Throttle debug output; do not log file names, data, users or keys. */
    if (total > 0 && (total % UF_LOG_INTERVAL) == 1) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID, DPFLTR_INFO_LEVEL,
            "UserFreezerAudit: attempted-major=%u sample-count=%ld (audit only)\n",
            (ULONG)major, total);
    }
    /* NEVER complete, pend, rewrite, deny or redirect an operation. */
    return FLT_PREOP_SUCCESS_NO_CALLBACK;
}

static
NTSTATUS
UfUnload(_In_ FLT_FILTER_UNLOAD_FLAGS Flags)
{
    UNREFERENCED_PARAMETER(Flags);
    if (gFilter != NULL) {
        FltUnregisterFilter(gFilter);
        gFilter = NULL;
    }
    DbgPrintEx(
        DPFLTR_IHVDRIVER_ID, DPFLTR_INFO_LEVEL,
        "UserFreezerAudit: unload attempts create=%ld write=%ld setinfo=%ld; no redirection\n",
        gCreates, gWrites, gSetInfo);
    return STATUS_SUCCESS;
}

static const FLT_OPERATION_REGISTRATION gCallbacks[] = {
    { IRP_MJ_CREATE, 0, UfObserveOnly, NULL },
    { IRP_MJ_WRITE, 0, UfObserveOnly, NULL },
    { IRP_MJ_SET_INFORMATION, 0, UfObserveOnly, NULL },
    { IRP_MJ_OPERATION_END }
};

static const FLT_REGISTRATION gRegistration = {
    sizeof(FLT_REGISTRATION),
    FLT_REGISTRATION_VERSION,
    0,
    NULL,
    gCallbacks,
    UfUnload,
    UfInstanceSetup
};

NTSTATUS
DriverEntry(
    _In_ PDRIVER_OBJECT DriverObject,
    _In_ PUNICODE_STRING RegistryPath
    )
{
    NTSTATUS status;

    gFilter = NULL;
    gCreates = gWrites = gSetInfo = 0;
    UfLoadLabConfig(RegistryPath);
    if (!gLabConfigured) {
        DbgPrintEx(
            DPFLTR_IHVDRIVER_ID, DPFLTR_WARNING_LEVEL,
            "UserFreezerAudit: missing lab opt-in; refusing driver start\n");
        return STATUS_ACCESS_DENIED;
    }

    status = FltRegisterFilter(DriverObject, &gRegistration, &gFilter);
    if (!NT_SUCCESS(status)) {
        gFilter = NULL;
        return status;
    }
    status = FltStartFiltering(gFilter);
    if (!NT_SUCCESS(status)) {
        FltUnregisterFilter(gFilter);
        gFilter = NULL;
    }
    return status;
}
