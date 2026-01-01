# SpotMe - FastAPI with MongoDB

A multi-tenant application for managing notes and executing sandboxed Python functions, built using FastAPI and MongoDB.

## Features

- **User Management**: Registration, authentication, and multi-tenancy support
- **Notes**: Create, read, update, and delete personal notes with tagging
- **Functions**: Define and execute sandboxed Python functions with two input methods:
  - Template syntax for non-programmers
  - Raw Python code for advanced users
- **Function Types**: Constraints, predicates, resolution, lambdas, custom, and generated functions
- **Multi-tenant Isolation**: Complete data separation between tenants
- **Admin Controls**: Global functions accessible across all tenants (admin-only)
- **Function Execution**: Safe execution with RestrictedPython sandbox
- **Function Composition**: Functions can call other functions
- **Interactive Testing**: Web-based function testing interface
- **Dashboard**: Centralized view of notes and functions with statistics
- **Comprehensive Logging**: Full audit trail
- **JWT Authentication**: Secure token-based authentication

## Setup

### Prerequisites

- Python 3.8+
- MongoDB (running locally or remote)

### Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file based on `.env.example`:
```bash
cp .env.example .env
```

3. Update the `.env` file with your configuration:
```
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=spotme
SECRET_KEY=your-secret-key-here-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

4. Ensure MongoDB is running

5. (Optional) Create an admin user to manage global functions:
```bash
python3 migrations/create_admin_user.py
```
Follow the prompts to create an admin account. Admin users can create global functions that are accessible across all tenants.

### Running the Application

```bash
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The application will be available at: http://localhost:8000

**Default Admin Credentials** (if you created an admin user):
- Email: `admin@example.com`
- Password: `admin123`
- Tenant ID: `default`

**Important**: Change the admin password immediately after first login in production environments.

## Usage

1. **Register**: Navigate to http://localhost:8000/register
   - Enter a tenant ID (e.g., "company1")
   - Provide your full name, email, and password
   - Click Register

2. **Login**: Navigate to http://localhost:8000/
   - Enter the same tenant ID used during registration
   - Provide your email and password
   - Click Login

3. **Dashboard**: After login, you'll be redirected to the dashboard
   - View statistics for your notes and functions
   - See recent activity
   - Quick access to create notes or functions

4. **Manage Notes**: Click "Notes" in the header
   - Click "New Note" to create a note
   - Click "Edit" on any note to modify it
   - Click "Delete" to remove a note
   - Use the search bar to find notes by title, content, or tags

5. **Manage Functions**: Click "Functions" in the header
   - Click "New Function" to create a function
   - Choose between Template Syntax or Raw Python
   - Set function type, scope (tenant or global), and return type
   - Click "Edit" to modify, "Delete" to remove, or "Test" to execute

6. **Test Functions**: Click "Test Functions" button
   - Select a function from the sidebar
   - Enter JSON context data
   - Click "Execute Function" to run it
   - View results, execution time, and any errors
   - Use "Replay" from history to re-run previous tests

## Multi-tenancy

The application supports multi-tenancy through tenant IDs. Users with different tenant IDs are completely isolated:
- Users can only see their own notes within their tenant
- Users can only see their own functions plus global functions
- Authentication is scoped to tenant ID
- All data is filtered by tenant ID
- Admin users can create global functions accessible to all tenants

## Functions - Comprehensive Guide

Functions in SpotMe allow you to define and execute sandboxed Python code safely. They are ideal for:
- **Constraints**: Validation rules (e.g., "debit must not exceed balance")
- **Predicates**: Boolean conditions (e.g., "is user eligible for discount?")
- **Resolution**: Decision logic (e.g., "calculate shipping fee based on weight")
- **Lambdas**: Simple transformations (e.g., "apply 2% service fee")
- **Custom**: Any business logic you need to execute dynamically

### Function Types

| Type | Purpose | Return Type | Example Use Case |
|------|---------|-------------|------------------|
| `constraints` | Validation rules that must be satisfied | boolean | "Transaction amount cannot exceed voucher balance" |
| `predicates` | Conditional checks | boolean | "Is user eligible for premium features?" |
| `resolution` | Decision-making logic | any | "Determine approval workflow based on amount" |
| `lambdas` | Simple transformations or calculations | any | "Calculate 2% service fee on transaction" |
| `custom` | User-defined business logic | any | "Complex multi-step calculations" |
| `generated` | AI or system-generated functions | any | "Functions created by automated processes" |

### Function Scopes

- **Tenant**: Private to your tenant. Only users in your tenant can see and execute these functions.
- **Global**: Created by admins. Accessible to all tenants across the system (read-only for non-admins).

### Code Input Methods

#### 1. Template Syntax (Recommended for Non-Programmers)

Template syntax provides a simple, domain-specific language for defining functions without writing Python code.

**Variable Access**: `$[variable.path]$`
```
$[transaction.amount]$        → ctx["transaction"]["amount"]
$[user.profile.age]$          → ctx["user"]["profile"]["age"]
$[voucher.balance]$           → ctx["voucher"]["balance"]
$[n]$                         → ctx["n"]

# Note: Both $[ctx.n]$ and $[n]$ work - "ctx." prefix is automatically stripped
$[ctx.amount]$                → ctx["amount"] (ctx prefix removed)
```

**Logical Operators**: `AND`, `OR`, `NOT`
```
$[x]$ > 0 AND $[y]$ < 100
$[status]$ == "active" OR $[status]$ == "pending"
NOT $[user.blocked]$
```

**Function Calls**: `^[function-id]^(args)`
```
^[fee-calculator]^($[amount]$)
^[validate-user]^($[user.id]$)
```

**Comparison Operators**: `==`, `!=`, `>`, `<`, `>=`, `<=`
```
$[age]$ >= 18
$[balance]$ != 0
$[score]$ > $[threshold]$
```

#### 2. Raw Python Code (Advanced Users)

For more complex logic, you can write raw Python code. Your code must define an `execute(ctx)` function:

```python
def execute(ctx):
    # Your logic here
    return result
```

### Template Syntax Examples

#### Example 1: Simple Balance Validation (Constraint)
**Business Rule**: "Debit amount must not exceed voucher balance and must be positive"

**Template Code**:
```
$[transaction.debit]$ <= $[voucher.balance]$ AND $[transaction.debit]$ > 0
```

**Compiled Python** (automatic):
```python
def execute(ctx):
    return ctx["transaction"]["debit"] <= ctx["voucher"]["balance"] and ctx["transaction"]["debit"] > 0
```

**Test Context**:
```json
{
  "transaction": {"debit": 50.0},
  "voucher": {"balance": 100.0}
}
```

**Result**: `true`

---

#### Example 2: Age Verification (Predicate)
**Business Rule**: "User must be at least 18 years old"

**Template Code**:
```
$[user.age]$ >= 18
```

**Test Context**:
```json
{
  "user": {"age": 25}
}
```

**Result**: `true`

---

#### Example 3: Multi-Condition Eligibility (Predicate)
**Business Rule**: "User is eligible if they are active, not blocked, and have a balance above minimum"

**Template Code**:
```
$[user.status]$ == "active" AND NOT $[user.blocked]$ AND $[user.balance]$ >= $[config.min_balance]$
```

**Test Context**:
```json
{
  "user": {
    "status": "active",
    "blocked": false,
    "balance": 500.0
  },
  "config": {
    "min_balance": 100.0
  }
}
```

**Result**: `true`

---

#### Example 4: Complex Business Logic (Resolution)
**Business Rule**: "Shipping is free if order exceeds $100, otherwise $10 for standard, $25 for express"

**Template Code**:
```
0 if $[order.total]$ >= 100 else (25 if $[order.shipping_type]$ == "express" else 10)
```

**Test Context 1** (Free shipping):
```json
{
  "order": {
    "total": 150.0,
    "shipping_type": "standard"
  }
}
```
**Result**: `0`

**Test Context 2** (Express shipping):
```json
{
  "order": {
    "total": 50.0,
    "shipping_type": "express"
  }
}
```
**Result**: `25`

---

### Raw Python Examples

#### Example 5: Service Fee Calculator (Lambda)
**Business Rule**: "Apply 2% service fee to transaction amount"

**Python Code**:
```python
def execute(ctx):
    amount = ctx['amount']
    fee_rate = 0.02
    return amount * fee_rate
```

**Test Context**:
```json
{
  "amount": 1000.0
}
```

**Result**: `20.0`

---

#### Example 6: Tiered Discount Calculator (Resolution)
**Business Rule**: "Discount based on purchase amount: 0% for <$100, 5% for $100-$500, 10% for $500-$1000, 15% for $1000+"

**Python Code**:
```python
def execute(ctx):
    amount = ctx['purchase']['amount']

    if amount < 100:
        discount_rate = 0.0
    elif amount < 500:
        discount_rate = 0.05
    elif amount < 1000:
        discount_rate = 0.10
    else:
        discount_rate = 0.15

    discount_amount = amount * discount_rate
    final_amount = amount - discount_amount

    return {
        'original_amount': amount,
        'discount_rate': discount_rate,
        'discount_amount': discount_amount,
        'final_amount': final_amount
    }
```

**Test Context**:
```json
{
  "purchase": {
    "amount": 750.0
  }
}
```

**Result**:
```json
{
  "original_amount": 750.0,
  "discount_rate": 0.1,
  "discount_amount": 75.0,
  "final_amount": 675.0
}
```

---

#### Example 7: Credit Score Evaluation (Predicate with Complex Logic)
**Business Rule**: "User is credit-approved if score >= 700 OR (score >= 650 AND income >= 50000 AND debt_ratio < 0.4)"

**Python Code**:
```python
def execute(ctx):
    score = ctx['credit']['score']
    income = ctx['user']['annual_income']
    debt_ratio = ctx['user']['debt_to_income_ratio']

    # Primary approval: high credit score
    if score >= 700:
        return True

    # Secondary approval: moderate score with good financials
    if score >= 650 and income >= 50000 and debt_ratio < 0.4:
        return True

    return False
```

**Test Context** (Approved via secondary criteria):
```json
{
  "credit": {"score": 680},
  "user": {
    "annual_income": 75000,
    "debt_to_income_ratio": 0.35
  }
}
```

**Result**: `true`

---

#### Example 8: Inventory Availability Check (Constraint)
**Business Rule**: "Order can be fulfilled if all items are in stock with sufficient quantity"

**Python Code**:
```python
def execute(ctx):
    order_items = ctx['order']['items']
    inventory = ctx['inventory']

    for item in order_items:
        product_id = item['product_id']
        requested_qty = item['quantity']

        # Check if product exists in inventory
        if product_id not in inventory:
            return False

        # Check if sufficient quantity available
        if inventory[product_id]['available'] < requested_qty:
            return False

    return True
```

**Test Context**:
```json
{
  "order": {
    "items": [
      {"product_id": "P001", "quantity": 5},
      {"product_id": "P002", "quantity": 3}
    ]
  },
  "inventory": {
    "P001": {"available": 10},
    "P002": {"available": 5}
  }
}
```

**Result**: `true`

---

### Function Composition (Calling Other Functions)

Functions can call other functions using the `^[function-id]^(args)` syntax in templates.

#### Example 9: Composed Validation

**Function 1** - `validate_amount` (ID: `67abc123...`):
```
$[amount]$ > 0 AND $[amount]$ <= 10000
```

**Function 2** - `validate_user_status` (ID: `67def456...`):
```
$[user.status]$ == "active" AND NOT $[user.suspended]$
```

**Function 3** - `complete_validation` (Composition):
```
^[67abc123...]^($[transaction.amount]$) AND ^[67def456...]^($[user]$)
```

**Test Context**:
```json
{
  "transaction": {"amount": 500.0},
  "user": {
    "status": "active",
    "suspended": false
  }
}
```

**Result**: `true` (both validations passed)

---

### Advanced Python Examples

#### Example 10: Date-Based Business Logic
**Business Rule**: "Calculate late fee based on days overdue (tiered rates)"

**Python Code**:
```python
def execute(ctx):
    from datetime import datetime

    due_date_str = ctx['invoice']['due_date']  # "2025-12-01"
    current_date_str = ctx['current_date']      # "2025-12-15"
    amount = ctx['invoice']['amount']

    # Parse dates
    due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
    current_date = datetime.strptime(current_date_str, '%Y-%m-%d')

    # Calculate days overdue
    days_overdue = (current_date - due_date).days

    if days_overdue <= 0:
        return {'late_fee': 0, 'days_overdue': 0, 'total': amount}

    # Tiered late fees
    if days_overdue <= 7:
        late_fee = amount * 0.01  # 1% for first week
    elif days_overdue <= 30:
        late_fee = amount * 0.05  # 5% for up to 30 days
    else:
        late_fee = amount * 0.10  # 10% beyond 30 days

    return {
        'late_fee': round(late_fee, 2),
        'days_overdue': days_overdue,
        'original_amount': amount,
        'total': round(amount + late_fee, 2)
    }
```

**Test Context**:
```json
{
  "invoice": {
    "due_date": "2025-12-01",
    "amount": 1000.0
  },
  "current_date": "2025-12-15"
}
```

**Result**:
```json
{
  "late_fee": 10.0,
  "days_overdue": 14,
  "original_amount": 1000.0,
  "total": 1010.0
}
```

---

#### Example 11: List Processing and Aggregation
**Business Rule**: "Calculate total order value with tax and apply bulk discount if applicable"

**Python Code**:
```python
def execute(ctx):
    items = ctx['order']['items']
    tax_rate = ctx['settings']['tax_rate']
    bulk_discount_threshold = ctx['settings']['bulk_discount_threshold']
    bulk_discount_rate = ctx['settings']['bulk_discount_rate']

    # Calculate subtotal
    subtotal = sum(item['price'] * item['quantity'] for item in items)

    # Apply bulk discount if threshold met
    if subtotal >= bulk_discount_threshold:
        discount = subtotal * bulk_discount_rate
        subtotal_after_discount = subtotal - discount
    else:
        discount = 0
        subtotal_after_discount = subtotal

    # Calculate tax
    tax = subtotal_after_discount * tax_rate

    # Calculate total
    total = subtotal_after_discount + tax

    return {
        'subtotal': round(subtotal, 2),
        'discount': round(discount, 2),
        'subtotal_after_discount': round(subtotal_after_discount, 2),
        'tax': round(tax, 2),
        'total': round(total, 2),
        'item_count': len(items)
    }
```

**Test Context**:
```json
{
  "order": {
    "items": [
      {"name": "Widget A", "price": 50.0, "quantity": 3},
      {"name": "Widget B", "price": 75.0, "quantity": 2}
    ]
  },
  "settings": {
    "tax_rate": 0.08,
    "bulk_discount_threshold": 200.0,
    "bulk_discount_rate": 0.10
  }
}
```

**Result**:
```json
{
  "subtotal": 300.0,
  "discount": 30.0,
  "subtotal_after_discount": 270.0,
  "tax": 21.6,
  "total": 291.6,
  "item_count": 2
}
```

---

### Security and Sandbox Restrictions

Functions run in a **RestrictedPython** sandbox with the following limitations:

**Allowed**:
- Basic math: `abs`, `max`, `min`, `round`, `sum`
- Type conversions: `str`, `int`, `float`, `bool`, `list`, `dict`
- Iterations: `len`, `range`, `sorted`, `any`, `all`
- Safe modules: `datetime` (via import)

**Blocked**:
- File I/O: `open`, `file`
- Code execution: `exec`, `eval`, `compile`, `__import__`
- System access: `vars`, `globals`, `locals`
- Network access
- Subprocess execution

**Resource Limits** (recommended for production):
- No built-in timeout (consider adding wrapper with timeout)
- No memory limits (consider using `resource` module)
- Suitable for **trusted users within tenants**
- For untrusted code, consider Docker/gVisor isolation

---

### Creating Functions via API

#### Create Template Function
```bash
curl -X POST "http://localhost:8000/api/functions/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "validate_debit",
    "description": "Ensures debit does not exceed balance",
    "function_type": "constraints",
    "scope": "tenant",
    "return_type": "boolean",
    "code_template": "$[transaction.debit]$ <= $[voucher.balance]$ AND $[transaction.debit]$ > 0",
    "tags": ["validation", "financial"]
  }'
```

#### Create Python Function
```bash
curl -X POST "http://localhost:8000/api/functions/" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "calculate_fee",
    "description": "Calculate 2% service fee",
    "function_type": "lambdas",
    "scope": "tenant",
    "return_type": "number",
    "code_python": "def execute(ctx):\n    return ctx[\"amount\"] * 0.02",
    "tags": ["calculation", "fees"]
  }'
```

#### Execute Function
```bash
curl -X POST "http://localhost:8000/api/functions/FUNCTION_ID/execute" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "context": {
      "transaction": {"debit": 50.0},
      "voucher": {"balance": 100.0}
    }
  }'
```

**Response**:
```json
{
  "result": true,
  "execution_time_ms": 1.23,
  "error": null
}
```

---

### Best Practices

1. **Start Simple**: Begin with template syntax for straightforward logic
2. **Test Thoroughly**: Use the testing interface to validate with multiple scenarios
3. **Use Descriptive Names**: Function names should clearly indicate their purpose
4. **Add Tags**: Organize functions with tags for easy searching
5. **Document Context Requirements**: Add clear descriptions of expected context structure
6. **Handle Edge Cases**: Test with edge cases (null values, empty lists, boundary conditions)
7. **Prefer Composition**: Break complex logic into smaller, reusable functions
8. **Set Return Types**: Explicitly declare return types for better validation
9. **Use Tenant Scope**: Keep functions tenant-scoped unless they truly need global access
10. **Monitor Execution Stats**: Check execution counts and performance in the dashboard

---

### Troubleshooting

**"Compilation Error"**:
- Check syntax in template (proper variable paths, balanced operators)
- Verify Python syntax if using raw code
- Ensure `execute(ctx)` function is defined in Python code

**"KeyError" during execution**:
- Verify context JSON contains all required fields
- Check variable paths match context structure
- Use "Load Example" button to see expected context format

**Function not appearing**:
- Verify function is marked as "Active"
- Check tenant scope (global functions only visible to admins for editing)
- Refresh the functions list

**Execution fails silently**:
- Check for compilation errors in function details
- Verify function hasn't been marked inactive
- Review execution logs for detailed error messages

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register a new user
- `POST /api/auth/login` - Login and receive JWT token

### Notes
- `POST /api/notes/` - Create a new note
- `GET /api/notes/` - Get all notes for current user
- `GET /api/notes/{note_id}` - Get a specific note
- `PUT /api/notes/{note_id}` - Update a note
- `DELETE /api/notes/{note_id}` - Delete a note
- `GET /api/notes/search/query?q={query}` - Search notes by title, content, or tags

### Functions
- `POST /api/functions/` - Create a new function (tenant or global if admin)
- `GET /api/functions/` - Get all functions (tenant + global functions)
- `GET /api/functions/{function_id}` - Get a specific function
- `PUT /api/functions/{function_id}` - Update a function (owner or admin only)
- `DELETE /api/functions/{function_id}` - Delete a function (owner or admin only)
- `POST /api/functions/{function_id}/execute` - Execute a function with context data
- `GET /api/functions/search/query?q={query}` - Search functions by name or description

### Web Pages
- `/` - Login page
- `/register` - User registration
- `/dashboard` - Main dashboard with stats and quick actions
- `/notes` - Notes management interface
- `/functions` - Functions management interface
- `/function-test` - Interactive function testing page

## Logging

Application logs are stored in the `logs/` directory:
- `logs/app.log` - Main application log with rotation (max 10MB per file, 5 backup files)

## Security Notes

### General Security
- Change the `SECRET_KEY` in production
- Use HTTPS in production
- Consider implementing rate limiting
- Regularly update dependencies
- Use strong passwords
- Change default admin credentials immediately

### Function Execution Security
- Functions run in **RestrictedPython** sandbox with limited builtins
- Suitable for **trusted users within tenants** (employees, team members)
- **NOT suitable for untrusted/public user code** without additional isolation
- No built-in timeout or memory limits (consider adding for production)
- File I/O, network access, and dangerous builtins are blocked
- For high-security environments, consider:
  - Docker/gVisor containers for function execution
  - Timeout wrappers to prevent infinite loops
  - Memory limits using `resource` module
  - Dedicated execution workers
- Admin review recommended before marking functions as "global"
- Monitor function execution logs for suspicious patterns

### Multi-Tenant Security
- All data is strictly isolated by `tenant_id`
- Users cannot access other tenants' data or functions
- Global functions are read-only for non-admin users
- Admin privileges should be granted carefully

## Technology Stack

### Backend
- **FastAPI**: Modern, fast web framework for building APIs
- **Motor**: Async MongoDB driver for Python
- **Pydantic**: Data validation using Python type annotations
- **RestrictedPython**: Secure Python code execution sandbox
- **python-jose**: JWT token creation and validation
- **passlib**: Password hashing with bcrypt

### Database
- **MongoDB**: NoSQL document database for storing users, notes, and functions
- Collections: `users`, `notes`, `functions`

### Frontend
- **Vanilla JavaScript**: No framework dependencies
- **Jinja2**: Server-side HTML templating
- **CSS Grid & Flexbox**: Responsive layouts

## Project Structure

```
alpha/
├── app/
│   ├── main.py                 # FastAPI application entry point
│   ├── database.py             # MongoDB connection and client
│   ├── models.py               # Pydantic models
│   ├── routes/
│   │   ├── auth.py             # Authentication endpoints
│   │   ├── notes.py            # Notes CRUD endpoints
│   │   └── functions.py        # Functions CRUD endpoints
│   ├── services/
│   │   ├── function_parser.py  # Template syntax parser
│   │   ├── function_executor.py # Function execution engine
│   │   └── restricted_executor.py # RestrictedPython wrapper
│   ├── utils/
│   │   └── admin.py            # Admin utilities
│   ├── templates/              # Jinja2 HTML templates
│   └── static/
│       └── css/
│           └── style.css       # Application styles
├── migrations/
│   └── create_admin_user.py    # Admin user creation script
├── logs/                       # Application logs (auto-created)
├── requirements.txt            # Python dependencies
├── .env.example               # Environment variables template
└── README.md                  # This file
```

## Contributing

This is a demonstration project showcasing:
- Multi-tenant SaaS architecture
- Sandboxed code execution
- Template-based DSL design
- Function composition patterns
- Secure authentication and authorization

Feel free to fork and extend for your own use cases!

## License

This project is provided as-is for educational and demonstration purposes.
