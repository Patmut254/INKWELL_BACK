from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from blog.views import (
    PostViewSet, CommentViewSet, CategoryViewSet, TagViewSet,
    RegisterView, verify_email, resend_verification,
    get_me, update_profile,
    get_all_users, delete_user, toggle_staff,
    send_contact, get_contact_messages, mark_contact_read,
    site_stats,
)

router = DefaultRouter()
router.register(r'posts', PostViewSet, basename='post')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'tags', TagViewSet, basename='tag')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),

    # Nested comments
    path('api/posts/<int:post_pk>/comments/', CommentViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('api/posts/<int:post_pk>/comments/<int:pk>/', CommentViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'})),

    # Auth
    path('api/auth/register/', RegisterView.as_view()),
    path('api/auth/verify-email/', verify_email),
    path('api/auth/resend-verification/', resend_verification),
    path('api/auth/login/', TokenObtainPairView.as_view()),
    path('api/auth/refresh/', TokenRefreshView.as_view()),
    path('api/auth/me/', get_me),
    path('api/auth/profile/', update_profile),

    # Admin
    path('api/admin/users/', get_all_users),
    path('api/admin/users/<int:pk>/delete/', delete_user),
    path('api/admin/users/<int:pk>/toggle-staff/', toggle_staff),
    path('api/admin/stats/', site_stats),
    path('api/admin/contacts/', get_contact_messages),
    path('api/admin/contacts/<int:pk>/read/', mark_contact_read),

    # Contact
    path('api/contact/', send_contact),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
