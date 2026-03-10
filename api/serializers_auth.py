"""
serializers_auth.py
    Authentication serializers for user registration and authentication.

Logic:
    Handles user registration with validation

Referenced by:
    views_auth.py
"""

from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password


class UserRegistrationSerializer(serializers.Serializer):
    """
    Serializer for user registration with password confirmation.
    """
    username = serializers.CharField(
        max_length=150,
        required=True,
        help_text="Required. 150 characters or fewer."
    )
    email = serializers.EmailField(
        required=True,
        help_text="Required. A valid email address."
    )
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        validators=[validate_password]
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    def validate_username(self, value):
        """Check that the username is not already taken."""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate_email(self, value):
        """Check that the email is not already registered."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, attrs):
        """Validate that passwords match."""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password_confirm": "Password fields didn't match."
            })
        return attrs

    def create(self, validated_data):
        """Create and return a new user."""
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        return user
