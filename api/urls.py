from django.urls import path
from api import views

urlpatterns = [
    path('plan-route/', views.plan_route, name='plan_route'),
    path('health/', views.health_check, name='health'),
    path('stations/', views.stations_preview, name='stations'),
]
