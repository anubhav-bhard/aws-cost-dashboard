import os
import boto3
import datetime
from flask import Flask, request, jsonify, render_template, url_for

# Load environment variables
AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AWS_ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "")

# Initialize clients
if not AWS_ACCESS_KEY or not AWS_SECRET_KEY:
    print("⚠️ WARNING: Missing AWS credentials. AWS calls will fail. Set via ENV variables.")
    client = None
    support_client = None
    compute_optimizer = None
else:
    print("✅ Access Key Loaded:", AWS_ACCESS_KEY[:4] + "****")
    client = boto3.client(
        'ce',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY
    )
    # Support client for Trusted Advisor (only available in us-east-1)
    support_client = boto3.client(
        'support',
        region_name='us-east-1',
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY
    ) if AWS_REGION else None
    
    # Compute Optimizer client
    compute_optimizer = boto3.client(
        'compute-optimizer',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY
    )

# Initialize Flask app
app = Flask(__name__)

# --- Helper Functions to Fetch Data ---
def fetch_daily_cost_data(num_days=30):
    if not client:
        raise Exception("AWS client not initialized. Check credentials.")
    
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=num_days)

    response = client.get_cost_and_usage(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='DAILY',
        Metrics=['UnblendedCost']
    )
    cost_data = [
        {
            'date': result['TimePeriod']['Start'],
            'cost': round(float(result['Total']['UnblendedCost']['Amount']), 2)
        }
        for result in response['ResultsByTime']
    ]
    total_cost = sum(item['cost'] for item in cost_data)
    return cost_data, total_cost

def fetch_service_cost_data(num_days=30):
    if not client:
        raise Exception("AWS client not initialized. Check credentials.")

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=num_days)
    
    response = client.get_cost_and_usage(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='MONTHLY',
        Metrics=['UnblendedCost'],
        GroupBy=[{
            'Type': 'DIMENSION',
            'Key': 'SERVICE'
        }]
    )
    
    service_costs = []
    if response['ResultsByTime'] and response['ResultsByTime'][0].get('Groups'):
        service_costs = sorted([
            {
                'service': group['Keys'][0],
                'cost': round(float(group['Metrics']['UnblendedCost']['Amount']), 2)
            }
            for group in response['ResultsByTime'][0]['Groups']
        ], key=lambda x: x['cost'], reverse=True)
    
    total_cost = sum(item['cost'] for item in service_costs)
    return service_costs, total_cost

def fetch_detailed_cost_data(num_days=30):
    """Fetch cost data with more granular details"""
    if not client:
        raise Exception("AWS client not initialized. Check credentials.")

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=num_days)
    
    response = client.get_cost_and_usage(
        TimePeriod={
            'Start': start_date.strftime('%Y-%m-%d'),
            'End': end_date.strftime('%Y-%m-%d')
        },
        Granularity='DAILY',
        Metrics=['UnblendedCost'],
        GroupBy=[
            {'Type': 'DIMENSION', 'Key': 'SERVICE'},
            {'Type': 'DIMENSION', 'Key': 'USAGE_TYPE'}
        ]
    )
    
    detailed_data = []
    for result in response['ResultsByTime']:
        date = result['TimePeriod']['Start']
        for group in result['Groups']:
            service = group['Keys'][0]
            usage_type = group['Keys'][1]
            cost = round(float(group['Metrics']['UnblendedCost']['Amount']), 2)
            detailed_data.append({
                'date': date,
                'service': service,
                'usage_type': usage_type,
                'cost': cost
            })
    
    return detailed_data

def fetch_cost_recommendations():
    """Fetch cost optimization recommendations"""
    recommendations = []
    
    # 1. Trusted Advisor Cost Optimization Checks
    if support_client:
        try:
            # Get cost optimization checks
            checks = support_client.describe_trusted_advisor_checks(language='en')['checks']
            cost_checks = [c for c in checks if c['category'] == 'cost_optimizing']
            
            # Get check results
            for check in cost_checks:
                result = support_client.describe_trusted_advisor_check_result(
                    checkId=check['id'],
                    language='en'
                )
                
                if 'result' in result and 'flaggedResources' in result['result']:
                    for resource in result['result']['flaggedResources']:
                        if resource['status'] == 'warning':
                            recommendations.append({
                                'type': 'Trusted Advisor',
                                'service': check['name'],
                                'description': resource.get('metadata', [''])[0],
                                'potential_savings': resource.get('metadata', ['', ''])[1] if len(resource.get('metadata', [])) > 1 else 'N/A'
                            })
        except Exception as e:
            print(f"Trusted Advisor error: {str(e)}")
    
    # 2. Compute Optimizer Recommendations
    if compute_optimizer:
        try:
            # EC2 instance recommendations
            ec2_response = compute_optimizer.get_ec2_instance_recommendations()
            for rec in ec2_response.get('instanceRecommendations', []):
                savings = rec.get('savingsOpportunity', {}).get('estimatedMonthlySavings', 0)
                if savings > 0:
                    recommendations.append({
                        'type': 'Compute Optimizer',
                        'service': 'EC2',
                        'description': f"Instance {rec['instanceArn'].split('/')[-1]} can be optimized",
                        'potential_savings': f"${savings:.2f}/month"
                    })
            
            # EBS volume recommendations
            ebs_response = compute_optimizer.get_ebs_volume_recommendations()
            for rec in ebs_response.get('volumeRecommendations', []):
                savings = rec.get('savingsOpportunity', {}).get('estimatedMonthlySavings', 0)
                if savings > 0:
                    recommendations.append({
                        'type': 'Compute Optimizer',
                        'service': 'EBS',
                        'description': f"Volume {rec['volumeArn'].split('/')[-1]} can be optimized",
                        'potential_savings': f"${savings:.2f}/month"
                    })
        except Exception as e:
            print(f"Compute Optimizer error: {str(e)}")
    
    return recommendations

# --- JSON API Endpoints ---
@app.route('/')
def home_page():
    return jsonify({
        "message": "✅ AWS Cost Explorer API is running.",
        "endpoints": {
            "daily_cost": "/cost/daily",
            "service_cost": "/cost/services",
            "detailed_cost": "/cost/detailed",
            "recommendations": "/cost/recommendations",
            "dashboard": "/dashboard",
            "insights_dashboard": "/insights"
        }
    })

@app.route('/cost/daily')
def get_daily_cost_json():
    try:
        days = request.args.get('days', default=30, type=int)
        cost_data, _ = fetch_daily_cost_data(days)
        return jsonify(cost_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/cost/services')
def get_service_cost_json():
    try:
        days = request.args.get('days', default=30, type=int)
        service_data, _ = fetch_service_cost_data(days)
        return jsonify(service_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/cost/detailed')
def get_detailed_cost_json():
    try:
        days = request.args.get('days', default=30, type=int)
        detailed_data = fetch_detailed_cost_data(days)
        return jsonify(detailed_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/cost/recommendations')
def get_recommendations_json():
    try:
        recommendations = fetch_cost_recommendations()
        return jsonify(recommendations)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- HTML Table View Endpoints ---
@app.route('/table/cost/daily')
def get_daily_cost_table():
    error_msg = None
    cost_data = []
    total_cost = 0
    days = request.args.get('days', default=30, type=int)
    try:
        if not client:
             raise Exception("AWS client not initialized. Check credentials.")
        cost_data, total_cost = fetch_daily_cost_data(days)
    except Exception as e:
        error_msg = str(e)
    return render_template('daily_cost_table.html', costs=cost_data, total_cost=total_cost, days=days, error=error_msg)

@app.route('/table/cost/services')
def get_service_cost_table():
    error_msg = None
    service_data = []
    total_cost = 0
    days = request.args.get('days', default=30, type=int)
    try:
        if not client:
             raise Exception("AWS client not initialized. Check credentials.")
        service_data, total_cost = fetch_service_cost_data(days)
    except Exception as e:
        error_msg = str(e)
    return render_template('service_cost_table.html', services=service_data, total_cost=total_cost, days=days, error=error_msg)

@app.route('/table/cost/detailed')
def get_detailed_cost_table():
    error_msg = None
    detailed_data = []
    days = request.args.get('days', default=30, type=int)
    try:
        if not client:
             raise Exception("AWS client not initialized. Check credentials.")
        detailed_data = fetch_detailed_cost_data(days)
    except Exception as e:
        error_msg = str(e)
    return render_template('detailed_cost_table.html', costs=detailed_data, days=days, error=error_msg)

@app.route('/table/cost/recommendations')
def get_recommendations_table():
    error_msg = None
    recommendations = []
    try:
        recommendations = fetch_cost_recommendations()
    except Exception as e:
        error_msg = str(e)
    return render_template('recommendations_table.html', recommendations=recommendations, error=error_msg)

# --- Dashboard Endpoints ---
@app.route('/dashboard')
def dashboard():
    error_msg = None
    days_param = request.args.get('days', default=30, type=int)
    
    daily_costs_for_chart = []
    total_daily_cost_sum = 0
    
    service_costs_for_chart = []
    total_service_cost_sum = 0
    
    daily_chart_days = min(days_param, 30)

    try:
        if not client:
            raise Exception("AWS client not initialized. Check credentials.")

        daily_costs_for_chart, total_daily_cost_sum = fetch_daily_cost_data(num_days=daily_chart_days)
        all_service_costs, total_service_cost_sum = fetch_service_cost_data(num_days=days_param)
        service_costs_for_chart = all_service_costs[:10]
    except Exception as e:
        error_msg = str(e)

    return render_template(
        'dashboard.html',
        error=error_msg,
        days_param=days_param,
        daily_costs_for_chart_days=daily_chart_days,
        daily_costs_for_chart=daily_costs_for_chart,
        total_daily_cost_sum=total_daily_cost_sum,
        service_costs_for_chart=service_costs_for_chart,
        total_service_cost_sum=total_service_cost_sum
    )

@app.route('/insights')
def insights_dashboard():
    """New insights dashboard with recommendations and detailed cost analysis"""
    error_msg = None
    days_param = request.args.get('days', default=30, type=int)
    
    # Cost data
    daily_costs = []
    service_costs = []
    detailed_costs = []
    recommendations = []
    total_daily_cost = 0
    total_service_cost = 0
    
    try:
        if client:
            daily_costs, total_daily_cost = fetch_daily_cost_data(num_days=min(days_param, 30))
            service_costs, total_service_cost = fetch_service_cost_data(num_days=days_param)
            detailed_costs = fetch_detailed_cost_data(days=7)[-7:]  # Last 7 days
        
        recommendations = fetch_cost_recommendations()
    except Exception as e:
        error_msg = str(e)
    
    # Prepare data for charts
    daily_chart_data = [{
        'date': item['date'], 
        'cost': item['cost']
    } for item in daily_costs]
    
    service_chart_data = [{
        'service': item['service'],
        'cost': item['cost']
    } for item in service_costs[:10]]  # Top 10 services
    
    # Group detailed costs by service for the chart
    service_details = {}
    for item in detailed_costs:
        service = item['service']
        if service not in service_details:
            service_details[service] = {'cost': 0, 'usage_types': {}}
        service_details[service]['cost'] += item['cost']
        
        # Track usage types
        usage_type = item['usage_type']
        if usage_type not in service_details[service]['usage_types']:
            service_details[service]['usage_types'][usage_type] = 0
        service_details[service]['usage_types'][usage_type] += item['cost']
    
    return render_template(
        'insights_dashboard.html',
        error=error_msg,
        days_param=days_param,
        daily_costs=daily_costs,
        total_daily_cost=total_daily_cost,
        service_costs=service_costs,
        total_service_cost=total_service_cost,
        detailed_costs=detailed_costs,
        service_details=service_details,
        recommendations=recommendations,
        daily_chart_data=daily_chart_data,
        service_chart_data=service_chart_data
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)