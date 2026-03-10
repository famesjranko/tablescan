"""
models.py
    Written by: Andrew McDonald
    Initial: 02.08.21
    Updated: 02.09.21
    version: 2.1

Logic:
    Handles/builds database model structures
    
Referenced by:
    serializers.py
"""

import os
from django.db import models
from django.db.models.deletion import SET_DEFAULT

from django.utils.encoding import force_text
import re

from pathlib import PurePath
from django.core.files.storage import FileSystemStorage


class MyStorage(FileSystemStorage):
    """
    User defined File System Storage Class
    """

    def get_available_name(self, name, max_length=None):
        """
        If a file name is already in use on storage, creates a converted String
        filename for the duplicate name, attaching '_!added!'
        >>> get_available_name("anz_2004.jpg")
        'anz_2004_!added!.jpg'
        """
        if self.exists(name):
            dir_name, file_name = PurePath(name).parts
            file_root = PurePath(file_name).stem
            file_ext = PurePath(file_name).suffix

            my_chars = "!added!"  # The characters you want to append

            name = PurePath(dir_name, "{}_{}{}".format(file_root, my_chars, file_ext))
        return name


def get_valid_filename(s):
    """
    Returns the given string converted to a string that can be used for a clean
    filename. Specifically, leading and trailing spaces are removed; other
    spaces are converted to underscores; and anything that is not a unicode
    alphanumeric, dash, underscore, or dot, is removed.
    >>> get_valid_filename("john's portrait in 2004.jpg")
    'johns_portrait_in_2004.jpg'
    """
    s = force_text(s).strip().replace(" ", "_")
    return re.sub(r"(?u)[^-\w.]", "", s)


def upload_path(instance, filename):
    """
    Returns a file directory path naming schema using the filename as parent
    directory
    >>> upload_path(Report, "anz_2004.pdf")
    'documents/anz_2004/anz_2004.pdf'
    """
    return "/".join(
        [str(get_valid_filename(instance.filename())), get_valid_filename(filename)]
    )


class Report(models.Model):
    """
    Report database Class Model
    """

    name = models.CharField(max_length=100, null=True)
    document = models.FileField(storage=MyStorage(), upload_to=upload_path)
    zip_csv = models.FileField(null=True)
    f_type = models.CharField(max_length=5, null=True)
    total_pages = models.PositiveIntegerField(null=True, blank=True)
    start_page = models.IntegerField(default=1)
    end_page = models.IntegerField(default=-1)

    # returns file name without .extension
    def filename(self):
        """
        Returns document filename without the .extension
        """
        return os.path.splitext(self.document.name)[0]

    def __unicode__(self):
        return "%s" % (self.document)

    def __str__(self):
        return "%s %s %s %s %s %s %s" % (
            self.id,
            self.name,
            self.document.url,
            self.f_type,
            self.total_pages,
            self.start_page,
            self.end_page,
        )


class Extracted(models.Model):
    """
    Extracted database Class Model
    """

    # The first element in each tuple is value that will be stored in the db.
    # The second element is displayed by the field’s form widget.
    FILE_CHOICES = ((".csv", "CSV"), (".json", "JSON"), (".xlsx", "XLSX"))

    report = models.ForeignKey(
        Report,
        db_column="document",
        related_name="extracted",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    page_num = models.PositiveIntegerField(
        null=True,
        blank=True,
    )
    table_num = models.PositiveIntegerField(
        null=True,
        blank=True,
    )
    file = models.FileField(
        null=True,
        blank=True,
    )
    f_type = models.CharField(max_length=5, null=True, blank=True, choices=FILE_CHOICES)

    def __str__(self):
        return "%s %s %s %s %s" % (
            self.page_num,
            self.table_num,
            self.f_type,
            self.file.name,
            self.file.url,
        )

    def __unicode__(self):
        return "%s" % (self.file)

    class Meta:
        ordering = ["page_num", "table_num", "f_type"]
