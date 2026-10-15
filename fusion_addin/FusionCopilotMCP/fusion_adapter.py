from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import adsk.core
import adsk.fusion

from fusion_copilot.task_controller import (
    Operation,
    TaskRequest,
    ValidationReport,
)


def _items(collection: Any):
    for index in range(collection.count):
        yield collection.item(index)


def _point_mm(point: adsk.core.Point3D) -> list[float]:
    return [round(point.x * 10.0, 6), round(point.y * 10.0, 6), round(point.z * 10.0, 6)]


def _required_text(arguments: Mapping[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _number(arguments: Mapping[str, Any], name: str, default: float | None = None) -> float:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _positive(arguments: Mapping[str, Any], name: str) -> float:
    value = _number(arguments, name)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _origin(arguments: Mapping[str, Any]) -> tuple[float, float, float]:
    value = arguments.get("origin_mm", [0.0, 0.0, 0.0])
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("origin_mm must contain exactly three numbers")
    coordinates: list[float] = []
    for coordinate in value:
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise ValueError("origin_mm must contain exactly three numbers")
        coordinates.append(float(coordinate))
    return coordinates[0], coordinates[1], coordinates[2]


def _local_app_data() -> Path:
    configured = os.environ.get("LOCALAPPDATA")
    if configured:
        return Path(configured)
    return Path.home() / "AppData" / "Local"


class FusionAdapter:
    """Adapter that implements modeling operations through Fusion's official interface."""

    def __init__(self, app: adsk.core.Application, ui: adsk.core.UserInterface) -> None:
        self._app = app
        self._ui = ui
        self._references: dict[str, str] = {}
        self.last_checkpoint: str | None = None
        self.last_validation = ValidationReport(passed=False, errors=("Not validated",))

    def _design(self) -> adsk.fusion.Design:
        design = adsk.fusion.Design.cast(self._app.activeProduct)
        if design is None:
            raise RuntimeError("The active Fusion document is not a design")
        return design

    def _root(self) -> adsk.fusion.Component:
        return self._design().rootComponent

    def request_task_approval(self, task: TaskRequest) -> bool:
        operations = "\n".join(
            f"  {index + 1}. {operation.name}"
            for index, operation in enumerate(task.operations)
        )
        message = (
            "Fusion Copilot exécutera la tâche complète suivante en une seule "
            "transaction :\n\n"
            f"{task.summary}\n\n"
            f"Opérations ({len(task.operations)}) :\n{operations}\n\n"
            "Une copie de récupération sera créée avant les modifications."
        )
        result = self._ui.messageBox(
            message,
            "Fusion Copilot — approbation de la tâche",
            adsk.core.MessageBoxButtonTypes.YesNoButtonType,
            adsk.core.MessageBoxIconTypes.QuestionIconType,
        )
        return result == adsk.core.DialogResults.DialogYes

    def create_checkpoint(self, task: TaskRequest) -> str:
        design = self._design()
        checkpoint_directory = _local_app_data() / "FusionCopilotMCP" / "checkpoints"
        checkpoint_directory.mkdir(parents=True, exist_ok=True)
        safe_task_id = re.sub(r"[^A-Za-z0-9._-]+", "-", task.task_id).strip("-")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = checkpoint_directory / f"{timestamp}_{safe_task_id or 'task'}.f3d"
        export_manager = design.exportManager
        options = export_manager.createFusionArchiveExportOptions(
            str(path),
            design.rootComponent,
        )
        if options is None or not export_manager.execute(options):
            raise RuntimeError("Fusion could not create the recovery checkpoint")
        self.last_checkpoint = str(path)
        return str(path)

    def begin_undo_group(self, task: TaskRequest) -> str:
        self._references.clear()
        return task.task_id

    def commit_undo_group(self, group_id: str) -> None:
        return

    def abort_undo_group(self, group_id: str) -> None:
        return

    def rollback_to_checkpoint(self, checkpoint_id: str) -> None:
        # The surrounding Fusion command marks executeFailed, which aborts the
        # command transaction. The exported checkpoint remains a second recovery path.
        return

    def execute_operation(self, operation: Operation) -> None:
        handlers = {
            "set_user_parameter": self._set_user_parameter,
            "create_box": self._create_box,
            "create_cylinder": self._create_cylinder,
            "cut_cylindrical_hole": self._cut_cylindrical_hole,
            "fillet_all_edges": self._fillet_all_edges,
            "rename_body": self._rename_body,
        }
        handler = handlers.get(operation.name)
        if handler is None:
            raise ValueError(f"Unsupported Fusion operation: {operation.name}")
        handler(operation.arguments)

    def validate_task(self, task: TaskRequest) -> ValidationReport:
        self.last_validation = self._validate_active_design()
        return self.last_validation

    def status(self, safety_mode: str) -> dict[str, Any]:
        document = self._app.activeDocument
        return {
            "ok": True,
            "connected": True,
            "addin_version": "0.1.0",
            "safety_mode": safety_mode,
            "active_document": document.name if document else None,
            "active_document_modified": bool(document and document.isModified),
            "supported_operations": [
                "set_user_parameter",
                "create_box",
                "create_cylinder",
                "cut_cylindrical_hole",
                "fillet_all_edges",
                "rename_body",
            ],
        }

    def inspect_design(self) -> dict[str, Any]:
        design = self._design()
        document = self._app.activeDocument
        components: list[dict[str, Any]] = []
        for component in _items(design.allComponents):
            brep_bodies = [self._describe_brep_body(body) for body in _items(component.bRepBodies)]
            mesh_bodies = [self._describe_mesh_body(body) for body in _items(component.meshBodies)]
            components.append(
                {
                    "name": component.name,
                    "brep_bodies": brep_bodies,
                    "mesh_bodies": mesh_bodies,
                }
            )

        parameters: list[dict[str, Any]] = []
        for parameter in _items(design.userParameters):
            parameters.append(
                {
                    "name": parameter.name,
                    "expression": parameter.expression,
                    "unit": parameter.unit,
                    "value": parameter.value,
                    "comment": parameter.comment,
                }
            )

        selection: list[dict[str, Any]] = []
        selections = self._ui.activeSelections
        for index in range(selections.count):
            entity = selections.item(index).entity
            selection.append(
                {
                    "type": entity.objectType,
                    "name": getattr(entity, "name", None),
                    "entity_token": getattr(entity, "entityToken", None),
                }
            )

        validation = self._validate_active_design()
        return {
            "ok": True,
            "document": {
                "name": document.name if document else None,
                "modified": bool(document and document.isModified),
            },
            "units": design.unitsManager.defaultLengthUnits,
            "timeline_count": design.timeline.count,
            "components": components,
            "user_parameters": parameters,
            "selection": selection,
            "validation": self.validation_dict(validation),
        }

    def validate_design(self) -> dict[str, Any]:
        report = self._validate_active_design()
        self.last_validation = report
        return {"ok": True, "validation": self.validation_dict(report)}

    def _set_user_parameter(self, arguments: Mapping[str, Any]) -> None:
        design = self._design()
        name = _required_text(arguments, "name")
        expression = _required_text(arguments, "expression")
        parameters = design.userParameters
        parameter = parameters.itemByName(name)
        if parameter is not None:
            parameter.expression = expression
            return
        units = str(arguments.get("units", "mm"))
        comment = str(arguments.get("comment", "Created by Fusion Copilot"))
        value = adsk.core.ValueInput.createByString(expression)
        if parameters.add(name, value, units, comment) is None:
            raise RuntimeError(f"Fusion could not create parameter {name}")

    def _plane_at_z(self, z_mm: float):
        root = self._root()
        if abs(z_mm) < 1e-9:
            return root.xYConstructionPlane
        plane_input = root.constructionPlanes.createInput()
        plane_input.setByOffset(
            root.xYConstructionPlane,
            adsk.core.ValueInput.createByString(f"{z_mm} mm"),
        )
        plane = root.constructionPlanes.add(plane_input)
        if plane is None:
            raise RuntimeError("Fusion could not create an offset construction plane")
        return plane

    def _create_box(self, arguments: Mapping[str, Any]) -> None:
        root = self._root()
        reference = _required_text(arguments, "reference")
        width_mm = _positive(arguments, "width_mm")
        depth_mm = _positive(arguments, "depth_mm")
        height_mm = _positive(arguments, "height_mm")
        origin_x, origin_y, origin_z = _origin(arguments)
        centered = bool(arguments.get("centered_xy", True))
        if centered:
            first = adsk.core.Point3D.create(
                (origin_x - width_mm / 2.0) / 10.0,
                (origin_y - depth_mm / 2.0) / 10.0,
                0,
            )
            second = adsk.core.Point3D.create(
                (origin_x + width_mm / 2.0) / 10.0,
                (origin_y + depth_mm / 2.0) / 10.0,
                0,
            )
        else:
            first = adsk.core.Point3D.create(origin_x / 10.0, origin_y / 10.0, 0)
            second = adsk.core.Point3D.create(
                (origin_x + width_mm) / 10.0,
                (origin_y + depth_mm) / 10.0,
                0,
            )
        sketch = root.sketches.add(self._plane_at_z(origin_z))
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(first, second)
        if sketch.profiles.count != 1:
            raise RuntimeError("The box sketch did not create exactly one profile")
        extrudes = root.features.extrudeFeatures
        feature = extrudes.addSimple(
            sketch.profiles.item(0),
            adsk.core.ValueInput.createByString(f"{height_mm} mm"),
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        )
        body = feature.bodies.item(0)
        body.name = str(arguments.get("name", reference))
        self._references[reference] = body.name

    def _create_cylinder(self, arguments: Mapping[str, Any]) -> None:
        root = self._root()
        reference = _required_text(arguments, "reference")
        diameter_mm = _positive(arguments, "diameter_mm")
        height_mm = _positive(arguments, "height_mm")
        origin_x, origin_y, origin_z = _origin(arguments)
        sketch = root.sketches.add(self._plane_at_z(origin_z))
        sketch.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(origin_x / 10.0, origin_y / 10.0, 0),
            diameter_mm / 20.0,
        )
        extrudes = root.features.extrudeFeatures
        feature = extrudes.addSimple(
            sketch.profiles.item(0),
            adsk.core.ValueInput.createByString(f"{height_mm} mm"),
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        )
        body = feature.bodies.item(0)
        body.name = str(arguments.get("name", reference))
        self._references[reference] = body.name

    def _body(self, reference: str) -> adsk.fusion.BRepBody:
        name = self._references.get(reference, reference)
        body = self._root().bRepBodies.itemByName(name)
        if body is None:
            raise ValueError(f"B-Rep body not found: {reference}")
        return body

    def _cut_cylindrical_hole(self, arguments: Mapping[str, Any]) -> None:
        root = self._root()
        target = self._body(_required_text(arguments, "target"))
        diameter_mm = _positive(arguments, "diameter_mm")
        center = arguments.get("center_mm", [0.0, 0.0])
        if not isinstance(center, list) or len(center) != 2:
            raise ValueError("center_mm must contain exactly two numbers")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in center):
            raise ValueError("center_mm must contain exactly two numbers")
        center_x = float(center[0])
        center_y = float(center[1])
        default_z_mm = target.boundingBox.minPoint.z * 10.0
        start_z_mm = _number(arguments, "start_z_mm", default_z_mm)
        sketch = root.sketches.add(self._plane_at_z(start_z_mm))
        sketch.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(center_x / 10.0, center_y / 10.0, 0),
            diameter_mm / 20.0,
        )
        extrudes = root.features.extrudeFeatures
        extrude_input = extrudes.createInput(
            sketch.profiles.item(0),
            adsk.fusion.FeatureOperations.CutFeatureOperation,
        )
        extrude_input.participantBodies = [target]
        through_all = adsk.fusion.ThroughAllExtentDefinition.create()
        extrude_input.setOneSideExtent(
            through_all,
            adsk.fusion.ExtentDirections.PositiveExtentDirection,
        )
        if extrudes.add(extrude_input) is None:
            raise RuntimeError("Fusion could not cut the cylindrical hole")

    def _fillet_all_edges(self, arguments: Mapping[str, Any]) -> None:
        root = self._root()
        target = self._body(_required_text(arguments, "target"))
        radius_mm = _positive(arguments, "radius_mm")
        edges = adsk.core.ObjectCollection.create()
        for edge in _items(target.edges):
            edges.add(edge)
        if edges.count == 0:
            raise ValueError("The target body has no edges to fillet")
        fillets = root.features.filletFeatures
        fillet_input = fillets.createInput()
        fillet_input.isRollingBallCorner = True
        fillet_input.edgeSetInputs.addConstantRadiusEdgeSet(
            edges,
            adsk.core.ValueInput.createByString(f"{radius_mm} mm"),
            True,
        )
        if fillets.add(fillet_input) is None:
            raise RuntimeError("Fusion could not create the fillet")

    def _rename_body(self, arguments: Mapping[str, Any]) -> None:
        reference = _required_text(arguments, "target")
        body = self._body(reference)
        body.name = _required_text(arguments, "name")
        self._references[reference] = body.name

    def _describe_brep_body(self, body: adsk.fusion.BRepBody) -> dict[str, Any]:
        bounds = body.boundingBox
        return {
            "name": body.name,
            "entity_token": body.entityToken,
            "solid": body.isSolid,
            "volume_mm3": round(body.volume * 1000.0, 6),
            "faces": body.faces.count,
            "edges": body.edges.count,
            "bounding_box_mm": {
                "min": _point_mm(bounds.minPoint),
                "max": _point_mm(bounds.maxPoint),
            },
        }

    def _describe_mesh_body(self, body: adsk.fusion.MeshBody) -> dict[str, Any]:
        description = {
            "name": body.name,
            "entity_token": body.entityToken,
            "closed": body.isClosed,
            "oriented": body.isOriented,
            "volume_mm3": round(body.volume * 1000.0, 6),
        }
        bounds = getattr(body, "boundingBox", None)
        if bounds is not None:
            description["bounding_box_mm"] = {
                "min": _point_mm(bounds.minPoint),
                "max": _point_mm(bounds.maxPoint),
            }
        return description

    def _validate_active_design(self) -> ValidationReport:
        design = self._design()
        errors: list[str] = []
        warnings: list[str] = []
        body_count = 0
        for component in _items(design.allComponents):
            for body in _items(component.bRepBodies):
                body_count += 1
                if not body.isValid:
                    errors.append(f"B-Rep body {body.name} is invalid")
                elif not body.isSolid:
                    errors.append(f"B-Rep body {body.name} is open")
            for body in _items(component.meshBodies):
                body_count += 1
                if not body.isValid:
                    errors.append(f"Mesh body {body.name} is invalid")
                if not body.isClosed:
                    errors.append(f"Mesh body {body.name} is open")
                if not body.isOriented:
                    errors.append(f"Mesh body {body.name} is not consistently oriented")
        if body_count == 0:
            warnings.append("The active design contains no bodies")
        return ValidationReport(
            passed=not errors,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    @staticmethod
    def validation_dict(report: ValidationReport) -> dict[str, Any]:
        return {
            "passed": report.passed,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
        }
