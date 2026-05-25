import os
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta
from courses.models import Payment

def generate_revenue_chart():
    # Make sure target directory exists
    charts_dir = os.path.join(settings.MEDIA_ROOT, 'charts')
    os.makedirs(charts_dir, exist_ok=True)
    chart_path = os.path.join(charts_dir, 'revenue_chart.png')
    
    # 1. Fetch real payment data
    today = timezone.now().date()
    start_date = today - timedelta(days=6)  # Last 7 days
    
    payments = Payment.objects.filter(
        status='completed',
        payment_date__date__range=[start_date, today]
    ).values('payment_date__date').annotate(daily_sum=Sum('amount')).order_by('payment_date__date')
    
    # Map real data into a dict
    real_data = {p['payment_date__date']: float(p['daily_sum']) for p in payments}
    
    # Create complete date range for last 7 days
    data_list = []
    for i in range(7):
        date = start_date + timedelta(days=i)
        val = real_data.get(date, 0.0)
        
        # If there are no real payments at all in the database, seed mock values so the chart is not blank
        if Payment.objects.count() == 0:
            # Mock baseline curve for demo purposes
            mock_vals = [120.0, 180.0, 150.0, 240.0, 210.0, 350.0, 420.0]
            val = mock_vals[i]
            
        data_list.append({'Date': date.strftime('%b %d'), 'Revenue': val})
        
    df = pd.DataFrame(data_list)
    
    # 2. Render plot with Seaborn
    plt.figure(figsize=(10, 4.5))
    sns.set_theme(style="white")
    
    # Define custom purple color palette
    purple_theme = "#8e44ad"
    blue_theme = "#3498db"
    
    # Line chart with filled area
    ax = sns.lineplot(
        x='Date', 
        y='Revenue', 
        data=df, 
        color=purple_theme, 
        linewidth=3.5, 
        marker='o', 
        markersize=8,
        markerfacecolor=blue_theme,
        markeredgecolor='white',
        markeredgewidth=2
    )
    
    # Fill the area under the curve
    x_coords = range(len(df))
    plt.fill_between(x_coords, df['Revenue'], color=purple_theme, alpha=0.12)
    
    # Premium styling details
    plt.title("Revenue Trend (Last 7 Days)", fontsize=14, fontweight='bold', pad=15, color='#2c3e50')
    plt.xlabel("")
    plt.ylabel("Revenue (₹)", fontsize=11, fontweight='bold', color='#2c3e50')
    plt.xticks(fontsize=10, fontweight='semibold', color='#7f8c8d')
    plt.yticks(fontsize=10, fontweight='semibold', color='#7f8c8d')
    
    # Style grid and borders
    sns.despine(left=True, bottom=True)
    plt.grid(axis='y', linestyle='--', alpha=0.5)
    
    plt.tight_layout()
    plt.savefig(chart_path, dpi=200, transparent=True)
    plt.close()
    
    return os.path.join(settings.MEDIA_URL, 'charts/revenue_chart.png').replace('\\', '/')
