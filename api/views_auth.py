"""
views_auth.py
    Authentication views for user registration and token management.

Logic:
    Handles user registration and login, returns JWT tokens and creates Django session

Referenced by:
    urls.py
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User

from .serializers_auth import UserRegistrationSerializer


class RegisterView(APIView):
    """
    User registration endpoint.

    POST /api/auth/register/

    Request body:
        - username: string (required)
        - email: string (required)
        - password: string (required)
        - password_confirm: string (required)

    Returns:
        - user: object with id, username, email
        - tokens: object with access and refresh tokens
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()

            # Create Django session (for frontend views)
            login(request, user)

            # Generate JWT tokens for the new user
            refresh = RefreshToken.for_user(user)

            return Response({
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                },
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                },
                'message': 'User registered successfully.'
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    """
    User login endpoint that creates both JWT tokens and Django session.

    POST /api/auth/login/

    Request body:
        - username: string (required)
        - password: string (required)

    Returns:
        - access: JWT access token
        - refresh: JWT refresh token
    """
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            return Response(
                {'detail': 'Username and password are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Create Django session (for frontend views)
            login(request, user)

            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)

            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            })
        else:
            return Response(
                {'detail': 'Invalid username or password.'},
                status=status.HTTP_401_UNAUTHORIZED
            )


class LogoutView(APIView):
    """
    User logout endpoint that clears the Django session.

    POST /api/auth/logout/
    """
    permission_classes = [AllowAny]

    def post(self, request):
        logout(request)
        return Response({'message': 'Logged out successfully.'})
