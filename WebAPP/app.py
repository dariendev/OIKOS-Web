from flask import Flask, render_template, request, redirect, url_for, session, abort, flash, send_from_directory
from werkzeug.utils import secure_filename
import secrets
import json
import os
import hashlib
import time
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'change_this_secret'

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

USERS_FILE = 'users.json'
GROUPS_FILE = 'groups.json'

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def load_data(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, 'r') as f:
        return json.load(f)

def save_data(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_password_hash, provided_password):
    return stored_password_hash == hash_password(provided_password)

def generate_invite_code():
    return secrets.token_hex(4)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
@app.route('/')
def index():
    users = load_data(USERS_FILE)
    return render_template('home.html', users=users)

@app.before_request
def require_login():
    if request.endpoint in ['index', 'about', 'login', 'register', 'static', 'uploaded_file']:
        return
    if 'username' not in session:
        return redirect(url_for('login'))

@app.template_filter('datetimeformat')
def datetimeformat(value):
    return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    username_input = request.form['username'].strip().lower()
    password_input = request.form['password']
    users = load_data(USERS_FILE)

    matched_username = next((u for u in users if u.lower() == username_input), None)

    if matched_username and verify_password(users[matched_username]['password'], password_input):
        session['username'] = matched_username
        session.pop('active_group', None)
        return redirect(url_for('dashboard'))

    return "Invalid credentials. <a href='/login'>Try again</a>"


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    username_input = request.form['username'].strip()
    username_key = username_input.lower()  # normalized key
    password = request.form['password']
    users = load_data(USERS_FILE)

    # Prevent duplicates (case-insensitive)
    if any(u.lower() == username_key for u in users):
        return "User already exists. <a href='/register'>Try another</a>"

    users[username_key] = {
        'password': hash_password(password),
        'profile_image': '',
        'real_name': username_input  # for display
    }

    save_data(USERS_FILE, users)
    return redirect(url_for('login'))

@app.route('/create_post')
def create_post():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('create_post.html')

@app.route('/delete_group/<group_id>', methods=['POST'])
def delete_group(group_id):
    username = session['username']
    groups = load_data(GROUPS_FILE)
    users = load_data(USERS_FILE)

    if group_id not in groups:
        return "Group not found. <a href='/dashboard'>Back</a>"

    if groups[group_id]['admin'] != username:
        return "Only the group admin can delete the group. <a href='/dashboard'>Back</a>"

    password_input = request.form.get('confirm_password', '')
    if not verify_password(users[username]['password'], password_input):
        return "Incorrect password. <a href='/dashboard'>Back</a>"

    del groups[group_id]
    save_data(GROUPS_FILE, groups)

    if session.get('active_group') == group_id:
        session.pop('active_group', None)

    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    username = session['username']
    users = load_data(USERS_FILE)
    groups = load_data(GROUPS_FILE)
    user_groups = {gid: group for gid, group in groups.items() if username in group.get('members', [])}

    if not user_groups:
        return render_template('dashboard_no_group.html', username=username)

    active_group = session.get('active_group')
    if active_group not in user_groups:
        active_group = next(iter(user_groups))
        session['active_group'] = active_group

    group = user_groups[active_group]
    group.setdefault('posts', [])
    group.setdefault('requests', [])

    page = int(request.args.get('page', 1))
    per_page = 5

    all_posts = list(reversed(group['posts']))  # newest to oldest
    total = len(all_posts)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_posts = all_posts[start:end]

    requests_list = group['requests'] if group['admin'] == username else []



    return render_template(
        'dashboard.html',
        username=username,
        user_groups=user_groups,
        active_group=active_group,
        group=group,
        users=users,
        requests_list=requests_list,
        posts=paginated_posts,
        page=page,
        total=total,
        per_page=per_page
    )



@app.route('/select_group', methods=['POST'])
def select_group():
    username = session['username']
    group_id = request.form.get('group_id')
    groups = load_data(GROUPS_FILE)
    if not group_id or group_id not in groups or username not in groups[group_id]['members']:
        return "Invalid group selection. <a href='/dashboard'>Back</a>"
    session['active_group'] = group_id
    return redirect(url_for('dashboard'))

@app.route('/create_group', methods=['GET', 'POST'])
def create_group():
    username = session['username']
    groups = load_data(GROUPS_FILE)

    if request.method == 'GET':
        return render_template('create_group.html')

    name = request.form['name']
    description = request.form['description']
    group_id = secrets.token_hex(6)
    invite_code = generate_invite_code()
    image_file = request.files.get('image')
    image_filename = ''

    if image_file and allowed_file(image_file.filename):
        image_filename = secure_filename(image_file.filename)
        image_file.save(os.path.join(UPLOAD_FOLDER, image_filename))

    groups[group_id] = {
        'admin': username,
        'invite_codes': [invite_code],
        'members': [username],
        'posts': [],
        'name': name,
        'description': description,
        'image': image_filename,
        'requests': []
    }
    save_data(GROUPS_FILE, groups)
    session['last_invite'] = (group_id, invite_code)
    session['active_group'] = group_id
    return redirect(url_for('dashboard'))

@app.route('/join_group', methods=['POST'])
def join_group():
    username = session['username']
    invite_code = request.form['invite_code'].strip()
    groups = load_data(GROUPS_FILE)
    for gid, group in groups.items():
        if invite_code in group['invite_codes']:
            if username in group['members'] or username in group.get('requests', []):
                return "You already requested or joined this group. <a href='/dashboard'>Back</a>"
            group.setdefault('requests', []).append(username)
            save_data(GROUPS_FILE, groups)
            return "Request sent. Wait for admin approval. <a href='/dashboard'>Back</a>"
    return "Invalid invite code. <a href='/dashboard'>Back</a>"

@app.route('/approve/<group_id>/<username_to_approve>', methods=['POST'])
def approve_user(group_id, username_to_approve):
    username = session['username']
    groups = load_data(GROUPS_FILE)
    if group_id in groups and groups[group_id]['admin'] == username:
        if username_to_approve in groups[group_id].get('requests', []):
            groups[group_id]['members'].append(username_to_approve)
            groups[group_id]['requests'].remove(username_to_approve)
            save_data(GROUPS_FILE, groups)
    return redirect(url_for('dashboard'))
@app.route('/deny/<group_id>/<username_to_deny>', methods=['POST'])
def deny_user(group_id, username_to_deny):
    username = session['username']
    groups = load_data(GROUPS_FILE)
    if group_id in groups and groups[group_id]['admin'] == username:
        if username_to_deny in groups[group_id].get('requests', []):
            groups[group_id]['requests'].remove(username_to_deny)
            save_data(GROUPS_FILE, groups)
    return redirect(url_for('dashboard'))


@app.route('/post/<group_id>', methods=['POST'])
def post_message(group_id):
    username = session['username']
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    images_files = request.files.getlist('images')

    if not title or not description:
        return "Title and description are required. <a href='/dashboard'>Back</a>"

    images_filenames = []
    for file in images_files[:4]:  # max 4 images
        if file and allowed_file(file.filename):
            filename = secure_filename(f"{secrets.token_hex(8)}_{file.filename}")
            file.save(os.path.join(UPLOAD_FOLDER, filename))
            images_filenames.append(filename)

    groups = load_data(GROUPS_FILE)
    if group_id in groups:
        group = groups[group_id]
        if username in group['members']:
            group.setdefault('posts', []).append({
                'author': username,
                'title': title,
                'description': description,
                'images': images_filenames,
                'timestamp': int(time.time()),
                'comments': []
            })
            save_data(GROUPS_FILE, groups)
            return redirect(url_for('dashboard'))
    return "Error posting. <a href='/dashboard'>Back</a>"

@app.route('/post/<group_id>/<int:post_index>', methods=['GET', 'POST'])
@app.route('/post/<group_id>/<int:post_index>', methods=['GET', 'POST'])
def view_post(group_id, post_index):
    username = session['username']
    groups = load_data(GROUPS_FILE)
    users = load_data(USERS_FILE)

    if group_id not in groups:
        return "Group not found. <a href='/dashboard'>Back</a>"
    group = groups[group_id]
    posts = list(reversed(group.get('posts', [])))  # same reversal as dashboard

    if post_index < 0 or post_index >= len(posts):
        return "Post not found. <a href='/dashboard'>Back</a>"

    post = posts[post_index]

    if request.method == 'POST':
        comment_text = request.form.get('comment', '').strip()
        anonymous = request.form.get('anonymous') == 'on'

        if comment_text:
            post.setdefault('comments', []).append({
                'author': 'Anonymous' if anonymous else username,
                'content': comment_text,
                'timestamp': int(time.time())
            })
            # Save to original post list (non-reversed)
            original_index = len(group['posts']) - 1 - post_index
            group['posts'][original_index] = post
            save_data(GROUPS_FILE, groups)
            return redirect(url_for('view_post', group_id=group_id, post_index=post_index))

    return render_template('post.html', post=post, users=users, group_id=group_id, post_index=post_index)

@app.route('/setup_pool/<group_id>', methods=['POST'])
def setup_pool(group_id):
    username = session['username']
    groups = load_data(GROUPS_FILE)

    if groups[group_id]['admin'] != username:
        return "Only admin can set up the pool. <a href='/dashboard'>Back</a>"

    name = request.form['pool_name']
    target = float(request.form['target'])

    groups[group_id]['pool'] = {
        'name': name,
        'target': target,
        'contributions': []
    }

    save_data(GROUPS_FILE, groups)
    return redirect(url_for('dashboard'))

@app.route('/contribute/<group_id>', methods=['POST'])
def contribute(group_id):
    username = session['username']
    amount = float(request.form['amount'])
    groups = load_data(GROUPS_FILE)

    if 'pool' not in groups[group_id]:
        return "No pool available. <a href='/dashboard'>Back</a>"

    groups[group_id]['pool']['contributions'].append({
        'user': username,
        'amount': amount,
        'approved': False
    })

    save_data(GROUPS_FILE, groups)
    return redirect(url_for('dashboard'))

@app.route('/approve_contrib/<group_id>/<int:index>', methods=['POST'])
def approve_contrib(group_id, index):
    username = session['username']
    groups = load_data(GROUPS_FILE)

    if groups[group_id]['admin'] != username:
        return "Only admin can approve. <a href='/dashboard'>Back</a>"

    contribs = groups[group_id]['pool']['contributions']
    if index < 0 or index >= len(contribs):
        return "Invalid index."

    new_amt = float(request.form.get('edit_amount', contribs[index]['amount']))
    if new_amt != contribs[index]['amount']:
        contribs[index]['amount'] = new_amt  # notify logic could go here
    contribs[index]['approved'] = True

    save_data(GROUPS_FILE, groups)
    return redirect(url_for('dashboard'))

    save_data(GROUPS_FILE, groups)
    return redirect(url_for('dashboard'))


@app.route('/delete_post/<group_id>/<int:post_index>', methods=['POST'])
def delete_post(group_id, post_index):
    username = session['username']
    groups = load_data(GROUPS_FILE)
    if group_id not in groups:
        return "Group not found. <a href='/dashboard'>Back</a>"
    group = groups[group_id]
    if group['admin'] != username:
        return "Only admin can delete posts. <a href='/dashboard'>Back</a>"
    if post_index < 0 or post_index >= len(group.get('posts', [])):
        return "Invalid post index. <a href='/dashboard'>Back</a>"
    group['posts'].pop(post_index)
    save_data(GROUPS_FILE, groups)
    return redirect(url_for('dashboard'))

@app.route('/leave_group/<group_id>', methods=['POST'])
def leave_group(group_id):
    username = session['username']
    groups = load_data(GROUPS_FILE)
    if group_id not in groups or username not in groups[group_id]['members']:
        return "Not a member of this group. <a href='/dashboard'>Back</a>"
    if groups[group_id]['admin'] == username:
        return "Admin can't leave their own group. Transfer admin or delete group. <a href='/dashboard'>Back</a>"
    groups[group_id]['members'].remove(username)
    save_data(GROUPS_FILE, groups)
    if session.get('active_group') == group_id:
        session.pop('active_group', None)
    return redirect(url_for('dashboard'))

@app.route('/kick_member/<group_id>/<member>', methods=['POST'])
def kick_member(group_id, member):
    username = session['username']
    groups = load_data(GROUPS_FILE)
    if group_id not in groups:
        return "Group not found. <a href='/dashboard'>Back</a>"
    group = groups[group_id]
    if group['admin'] != username:
        return "Only admin can kick members. <a href='/dashboard'>Back</a>"
    if member == username:
        return "Admin cannot kick themselves. <a href='/dashboard'>Back</a>"
    if member not in group['members']:
        return "User not in group. <a href='/dashboard'>Back</a>"
    group['members'].remove(member)
    save_data(GROUPS_FILE, groups)
    return redirect(url_for('dashboard'))

@app.route('/generate_invite/<group_id>', methods=['POST'])
def generate_invite(group_id):
    username = session['username']
    groups = load_data(GROUPS_FILE)
    if group_id not in groups or groups[group_id]['admin'] != username:
        return "Unauthorized. <a href='/dashboard'>Back</a>"

    new_code = generate_invite_code()
    groups[group_id].setdefault('invite_codes', []).append(new_code)
    save_data(GROUPS_FILE, groups)
    session['last_invite'] = (group_id, new_code)
    return redirect(url_for('dashboard'))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    username = session['username']
    users = load_data(USERS_FILE)

    if request.method == 'POST':
        new_name = request.form['real_name']
        new_username = request.form['new_username']
        new_password = request.form['new_password']
        profile_img = request.files.get('profile_image')

        # Normalize the new username
        if new_username and new_username.lower() != username.lower():
            new_username_key = new_username.lower()

            if any(u.lower() == new_username_key for u in users):
                return "Username already exists."

            # Move user data to new key
            users[new_username_key] = users.pop(username)
            users[new_username_key]['real_name'] = new_username  # update display name

            session['username'] = new_username_key
            username = new_username_key

        if new_password:
            users[username]['password'] = hash_password(new_password)

        if profile_img and allowed_file(profile_img.filename):
            filename = secure_filename(profile_img.filename)
            profile_img.save(os.path.join(UPLOAD_FOLDER, filename))
            users[username]['profile_image'] = filename

        users[username]['real_name'] = new_name
        save_data(USERS_FILE, users)
        return redirect(url_for('profile'))

    return render_template('profile.html', user=users[username], username=username)


if __name__ == '__main__':
    app.run(debug=True)

