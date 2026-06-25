from __future__ import annotations

from dataclasses import dataclass

from .advanced_obd import DiagnosticError, IsoTpLiteClient, read_uds_did


@dataclass(frozen=True)
class UdsDidDefinition:
    did: int
    name: str
    decode_ascii: bool = True


@dataclass(frozen=True)
class UdsDidRead:
    did: int
    name: str
    data: bytes | None
    error: str | None = None

    def as_event(self) -> dict[str, object]:
        event: dict[str, object] = {
            "did": f"{self.did:04X}",
            "name": self.name,
        }
        if self.data is None:
            event["error"] = self.error or "not available"
            return event

        event["data"] = self.data.hex().upper()
        event["ascii"] = bytes_to_printable_ascii(self.data)
        return event


COMMON_UDS_DIDS = [
    UdsDidDefinition(0xF180, "bootSoftwareIdentification"),
    UdsDidDefinition(0xF181, "applicationSoftwareIdentification"),
    UdsDidDefinition(0xF182, "applicationDataIdentification"),
    UdsDidDefinition(0xF187, "vehicleManufacturerSparePartNumber"),
    UdsDidDefinition(0xF188, "vehicleManufacturerEcuSoftwareNumber"),
    UdsDidDefinition(0xF189, "vehicleManufacturerEcuSoftwareVersion"),
    UdsDidDefinition(0xF18A, "systemSupplierIdentifier"),
    UdsDidDefinition(0xF18B, "ecuManufacturingDate"),
    UdsDidDefinition(0xF18C, "ecuSerialNumber"),
    UdsDidDefinition(0xF190, "vin"),
    UdsDidDefinition(0xF191, "vehicleManufacturerEcuHardwareNumber"),
    UdsDidDefinition(0xF192, "systemSupplierEcuHardwareNumber"),
    UdsDidDefinition(0xF193, "systemSupplierEcuHardwareVersion"),
    UdsDidDefinition(0xF194, "systemSupplierEcuSoftwareNumber"),
    UdsDidDefinition(0xF195, "systemSupplierEcuSoftwareVersion"),
    UdsDidDefinition(0xF197, "systemNameOrEngineType"),
]


def scan_common_uds_dids(
    client: IsoTpLiteClient,
    tx_id: int,
    rx_id: int,
    definitions: list[UdsDidDefinition] | None = None,
) -> list[UdsDidRead]:
    reads: list[UdsDidRead] = []
    for definition in definitions or COMMON_UDS_DIDS:
        try:
            data = read_uds_did(client, tx_id=tx_id, rx_id=rx_id, did=definition.did)
            reads.append(UdsDidRead(did=definition.did, name=definition.name, data=data))
        except DiagnosticError as error:
            reads.append(UdsDidRead(did=definition.did, name=definition.name, data=None, error=str(error)))
    return reads


def bytes_to_printable_ascii(data: bytes) -> str:
    return "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in data)
