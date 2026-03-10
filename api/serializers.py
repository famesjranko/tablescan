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
from .models import *


class ExtractedSerializer(serializers.HyperlinkedModelSerializer):
    """
    Extracted Model Serializer
    """

    # link Extracted to it's connected Report model
    report = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Extracted
        fields = ("report", "page_num", "table_num", "f_type", "file")


class ReportSerializer2(serializers.ModelSerializer):
    """
    Report Model Serializer 2
    """

    # link Report to it's connected Extracted model
    extracted = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="file"
    )  # send raw json

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
        )


class ExtractedSerializer2(serializers.HyperlinkedModelSerializer):
    """
    Extracted Model Serializer 2
    """

    class Meta:
        model = Extracted
        fields = ("page_num", "table_num", "f_type", "file")


class ReportSerializer(serializers.ModelSerializer):
    """
    Report Model Serializer
    """

    # link Report to it's connected Extracted model
    extracted = ExtractedSerializer2(read_only=True, many=True)

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
        )
