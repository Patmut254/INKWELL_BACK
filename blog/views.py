from rest_framework import viewsets, generics, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth.models import User
from django.utils.text import slugify
from django.db.models import Q
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Post, Comment, Category, Tag, UserProfile, EmailVerification, ContactMessage
from .serializers import (
    PostSerializer, CommentSerializer, CategorySerializer, TagSerializer,
    UserSerializer, RegisterSerializer, ContactMessageSerializer
)


# ─── AUTH ────────────────────────────────────────────────────────────────────

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Generate 6-digit code
        code = EmailVerification.generate_code()
        EmailVerification.objects.update_or_create(
            user=user,
            defaults={'code': code, 'is_used': False}
        )

        # Send verification email
        try:
            send_mail(
                subject='Verify your Inkwell account',
                message=(
                    f'Hi {user.first_name or user.username},\n\n'
                    f'Your Inkwell verification code is:\n\n'
                    f'  {code}\n\n'
                    f'This code expires in 30 minutes.\n\n'
                    f'If you did not register, please ignore this email.\n\n'
                    f'— The Inkwell Team'
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            pass

        return Response(
            {'message': 'Account created. Check your email for a 6-digit verification code.', 'username': user.username},
            status=status.HTTP_201_CREATED
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_email(request):
    username = request.data.get('username')
    code = request.data.get('code', '').strip()
    try:
        user = User.objects.get(username=username)
        verification = user.email_verification
    except (User.DoesNotExist, EmailVerification.DoesNotExist):
        return Response({'error': 'Invalid request.'}, status=400)

    if verification.is_used:
        return Response({'error': 'Code already used.'}, status=400)
    if verification.is_expired():
        return Response({'error': 'Code has expired. Request a new one.'}, status=400)
    if verification.code != code:
        return Response({'error': 'Incorrect code.'}, status=400)

    user.is_active = True
    user.save()
    verification.is_used = True
    verification.save()
    user.profile.is_email_verified = True
    user.profile.save()

    return Response({'message': 'Email verified. You can now sign in.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def resend_verification(request):
    username = request.data.get('username')
    try:
        user = User.objects.get(username=username, is_active=False)
    except User.DoesNotExist:
        return Response({'error': 'User not found or already verified.'}, status=400)

    code = EmailVerification.generate_code()
    EmailVerification.objects.update_or_create(
        user=user,
        defaults={'code': code, 'is_used': False}
    )

    try:
        send_mail(
            subject='Your new Inkwell verification code',
            message=(
                f'Hi {user.first_name or user.username},\n\n'
                f'Your new verification code is:\n\n'
                f'  {code}\n\n'
                f'This code expires in 30 minutes.\n\n'
                f'— The Inkwell Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception:
        pass

    return Response({'message': 'New code sent to your email.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_me(request):
    return Response(UserSerializer(request.user).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    profile = request.user.profile
    user = request.user
    allowed_user = ['first_name', 'last_name']
    allowed_profile = ['bio', 'avatar', 'website', 'twitter', 'location']
    for field in allowed_user:
        if field in request.data:
            setattr(user, field, request.data[field])
    user.save()
    for field in allowed_profile:
        if field in request.data:
            setattr(profile, field, request.data[field])
    profile.save()
    return Response(UserSerializer(user).data)


# ─── ADMIN USER MANAGEMENT ───────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_all_users(request):
    users = User.objects.all().order_by('-date_joined')
    return Response(UserSerializer(users, many=True).data)


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def delete_user(request, pk):
    try:
        user = User.objects.get(pk=pk)
        if user == request.user:
            return Response({'error': 'Cannot delete yourself.'}, status=400)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    except User.DoesNotExist:
        return Response({'error': 'User not found.'}, status=404)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def toggle_staff(request, pk):
    try:
        user = User.objects.get(pk=pk)
        if user == request.user:
            return Response({'error': 'Cannot change your own role.'}, status=400)
        user.is_staff = not user.is_staff
        user.save()
        return Response(UserSerializer(user).data)
    except User.DoesNotExist:
        return Response({'error': 'User not found.'}, status=404)


# ─── CATEGORIES ──────────────────────────────────────────────────────────────

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAdminUser()]
        return [AllowAny()]

    def perform_create(self, serializer):
        name = serializer.validated_data.get('name', '')
        base_slug = slugify(name)
        slug = base_slug
        i = 1
        while Category.objects.filter(slug=slug).exists():
            slug = f'{base_slug}{i}'
            i += 1
        serializer.save(slug=slug)

    def perform_update(self, serializer):
        instance = self.get_object()
        name = serializer.validated_data.get('name', instance.name)
        base_slug = slugify(name)
        slug = base_slug
        i = 1
        while Category.objects.filter(slug=slug).exclude(pk=instance.pk).exists():
            slug = f'{base_slug}{i}'
            i += 1
        serializer.save(slug=slug)


# ─── TAGS ─────────────────────────────────────────────────────────────────────

class TagViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [AllowAny]


# ─── POSTS ───────────────────────────────────────────────────────────────────

class PostViewSet(viewsets.ModelViewSet):
    serializer_class = PostSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and user.is_staff:
            qs = Post.objects.all()
        else:
            qs = Post.objects.filter(status='published')

        search = self.request.query_params.get('search', '')
        category = self.request.query_params.get('category', '')
        author = self.request.query_params.get('author', '')
        tag = self.request.query_params.get('tag', '')

        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(content__icontains=search) | Q(excerpt__icontains=search))
        if category:
            qs = qs.filter(category__slug=category)
        if author:
            qs = qs.filter(author__username=author)
        if tag:
            qs = qs.filter(tags__slug=tag)
        return qs.select_related('author', 'category').prefetch_related('likes', 'comments', 'tags')

    def get_serializer_context(self):
        return {'request': self.request}

    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated()]
        if self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated()]
        return [AllowAny()]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.increment_views()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        title = serializer.validated_data.get('title', '')
        base_slug = slugify(title)
        slug = base_slug
        i = 1
        while Post.objects.filter(slug=slug).exists():
            slug = f'{base_slug}{i}'
            i += 1
        serializer.save(author=self.request.user, slug=slug)

    def update(self, request, *args, **kwargs):
        post = self.get_object()
        if not (request.user == post.author or request.user.is_staff):
            return Response({'error': 'Not authorized.'}, status=403)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        post = self.get_object()
        if not (request.user == post.author or request.user.is_staff):
            return Response({'error': 'Not authorized.'}, status=403)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        post = self.get_object()
        if post.likes.filter(id=request.user.id).exists():
            post.likes.remove(request.user)
            liked = False
        else:
            post.likes.add(request.user)
            liked = True
        return Response({'liked': liked, 'like_count': post.likes.count()})

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_posts(self, request):
        posts = Post.objects.filter(author=request.user).order_by('-created_at')
        serializer = self.get_serializer(posts, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def trending(self, request):
        posts = Post.objects.filter(status='published').order_by('-views', '-created_at')[:6]
        serializer = self.get_serializer(posts, many=True)
        return Response(serializer.data)


# ─── COMMENTS ─────────────────────────────────────────────────────────────────

class CommentViewSet(viewsets.ModelViewSet):
    serializer_class = CommentSerializer

    def get_queryset(self):
        return Comment.objects.filter(post_id=self.kwargs.get('post_pk')).select_related('author', 'author__profile')

    def get_serializer_context(self):
        return {'request': self.request}

    def get_permissions(self):
        if self.action == 'list':
            return [AllowAny()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        post = Post.objects.get(pk=self.kwargs.get('post_pk'))
        serializer.save(author=self.request.user, post=post)

    def update(self, request, *args, **kwargs):
        comment = self.get_object()
        if not (request.user == comment.author or request.user.is_staff):
            return Response({'error': 'Not authorized.'}, status=403)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        comment = self.get_object()
        if not (request.user == comment.author or request.user.is_staff):
            return Response({'error': 'Not authorized.'}, status=403)
        return super().destroy(request, *args, **kwargs)


# ─── CONTACT ─────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def send_contact(request):
    serializer = ContactMessageSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    msg = serializer.save()

    # Email to site owner
    try:
        send_mail(
            subject=f'[Inkwell Contact] {msg.subject}',
            message=(
                f'From: {msg.name} <{msg.email}>\n'
                f'Subject: {msg.subject}\n\n'
                f'{msg.message}\n\n'
                f'---\nReceived at {msg.created_at.strftime("%Y-%m-%d %H:%M")} EAT'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.CONTACT_EMAIL],
            fail_silently=True,
        )
        # Auto-reply to sender
        send_mail(
            subject='Thanks for reaching out — Inkwell',
            message=(
                f'Hi {msg.name},\n\n'
                f'Thanks for your message! We\'ve received it and will get back to you soon.\n\n'
                f'Your message:\n"{msg.message}"\n\n'
                f'You can also reach us directly at:\n'
                f'  Email: {settings.CONTACT_EMAIL}\n'
                f'  Phone: {settings.CONTACT_PHONE}\n\n'
                f'— Anita, Inkwell\n'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[msg.email],
            fail_silently=True,
        )
    except Exception:
        pass

    return Response({'message': 'Message sent! We\'ll get back to you soon.'}, status=201)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def get_contact_messages(request):
    messages = ContactMessage.objects.all()
    serializer = ContactMessageSerializer(messages, many=True)
    return Response(serializer.data)


@api_view(['PATCH'])
@permission_classes([IsAdminUser])
def mark_contact_read(request, pk):
    try:
        msg = ContactMessage.objects.get(pk=pk)
        msg.is_read = True
        msg.save()
        return Response({'message': 'Marked as read.'})
    except ContactMessage.DoesNotExist:
        return Response({'error': 'Not found.'}, status=404)


# ─── STATS ───────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def site_stats(request):
    from django.db.models import Sum
    return Response({
        'total_users': User.objects.count(),
        'total_posts': Post.objects.count(),
        'published_posts': Post.objects.filter(status='published').count(),
        'total_comments': Comment.objects.count(),
        'total_views': Post.objects.aggregate(v=Sum('views'))['v'] or 0,
        'total_categories': Category.objects.count(),
        'unread_messages': ContactMessage.objects.filter(is_read=False).count(),
    })
