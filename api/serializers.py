"""
serializers.py
    Written by: Andrew McDonald
    Initial: 03.08.21
    Updated: 02.09.21
    version: 1.9

Logic:
    Handles database model structures for API

Calls on:
    models.py
    
Referenced by:
    views.py
"""

from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from .models import *


class ExtractedSerializer(serializers.HyperlinkedModelSerializer):
    """
    Extracted Model Serializer
    """

    # link Extracted to it's connected Report model
    report = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Extracted
        fields = (
            "report",
            "page_num",
            "table_num",
            "f_type",
            "file",
            # Rich metadata fields (US-019)
            "page_type",
            "extraction_method",
            "confidence_score",
        )


class ExtractedSerializer2(serializers.HyperlinkedModelSerializer):
    """
    Extracted Model Serializer 2
    Used by ReportSerializer for nested extracted table data
    """

    class Meta:
        model = Extracted
        fields = (
            "page_num",
            "table_num",
            "f_type",
            "file",
            # Rich metadata fields (US-019)
            "page_type",
            "extraction_method",
            "confidence_score",
        )


class ReportSerializer(serializers.ModelSerializer):
    """
    Report Model Serializer
    """

    # link Report to it's connected Extracted model
    extracted = ExtractedSerializer2(read_only=True, many=True)

    # Expose the owner's username as a read-only field
    owner = serializers.ReadOnlyField(source='owner.username')

    class Meta:
        model = Report
        fields = (
            "id",
            "name",
            "f_type",
            "document",
            "zip_csv",
            "total_pages",
            "start_page",
            "end_page",
            "extracted",
            "owner",
        )


class TableSelectionSerializer(serializers.ModelSerializer):
    """
    TableSelection Model Serializer for CRUD operations
    """

    report = serializers.PrimaryKeyRelatedField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = TableSelection
        fields = (
            "id",
            "report",
            "page_num",
            "x1",
            "y1",
            "x2",
            "y2",
            "confidence",
            "source",
            "status",
            "created_at",
        )

    def validate(self, attrs):
        # Validate box orientation: x1 < x2 and y1 < y2
        x1 = attrs.get("x1")
        y1 = attrs.get("y1")
        x2 = attrs.get("x2")
        y2 = attrs.get("y2")

        if x1 is not None and x2 is not None and x1 >= x2:
            raise ValidationError({"x2": "x2 must be greater than x1."})
        if y1 is not None and y2 is not None and y1 >= y2:
            raise ValidationError({"y2": "y2 must be greater than y1."})

        # Validate page_num is within report's total_pages
        page_num = attrs.get("page_num")
        report = self.context.get("report")
        if report and page_num is not None:
            if report.total_pages is not None and page_num > report.total_pages:
                raise ValidationError({
                    "page_num": f"page_num must not exceed report's total_pages ({report.total_pages})."
                })
            if page_num < 1:
                raise ValidationError({"page_num": "page_num must be at least 1."})

        return attrs

    def create(self, validated_data):
        # Set default source to 'manual' if not provided
        if "source" not in validated_data or validated_data.get("source") is None:
            validated_data["source"] = "manual"

        # Set default status based on source
        if "status" not in validated_data or validated_data.get("status") is None:
            if validated_data.get("source") == "manual":
                validated_data["status"] = "approved"
            else:
                validated_data["status"] = "pending"

        return super().create(validated_data)
