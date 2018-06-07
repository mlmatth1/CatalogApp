from flask import Flask, render_template, request, redirect, jsonify, url_for, flash
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from catagories_database_setup import Base, Catagories, CatagoryItem, User
from flask import session as login_session
import random
import string
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Catelog Application"

# Connect to Database and create database session
engine = create_engine('sqlite:///catagories.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()

# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login.html', STATE=state)

@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps('Current user is already connected.'),
                                 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
        print user_id
    login_session['user_id'] = user_id

    creator = getUserInfo(user_id)

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    output += '<h1>Your ID is: %s ' % user_id

    flash("you are now logged in as %s" % login_session['username'])
    return output

    #return render_template('publicmenu.html', items = items, restaurant = restaurant, creator=creator)

# DISCONNECT - Revoke a current user's token and reset their login_session
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print 'Access Token is None'
        response = make_response(json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response

@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = request.data
    print "access token received %s " % access_token

    app_id = json.loads(open('fb_client_secrets.json', 'r').read())[
        'web']['app_id']
    app_secret = json.loads(
        open('fb_client_secrets.json', 'r').read())['web']['app_secret']
    url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (
        app_id, app_secret, access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]

    # Use token to get user info from API
    userinfo_url = "https://graph.facebook.com/v2.8/me"
    '''
        Due to the formatting for the result from the server token exchange we have to
        split the token first on commas and select the first index which gives us the key : value
        for the server access token then we split it on colons to pull out the actual token value
        and replace the remaining quotes with nothing so that it can be used directly in the graph
        api calls
    '''
    token = result.split(',')[0].split(':')[1].replace('"', '')

    url = 'https://graph.facebook.com/v2.8/me?access_token=%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    # print "url sent for API access:%s"% url
    # print "API JSON result: %s" % result
    data = json.loads(result)
    login_session['provider'] = 'facebook'
    login_session['username'] = data["name"]
    login_session['email'] = data["email"]
    login_session['facebook_id'] = data["id"]

    # The token must be stored in the login_session in order to properly logout
    login_session['access_token'] = token

    # Get user picture
    url = 'https://graph.facebook.com/v2.8/me/picture?access_token=%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)

    login_session['picture'] = data["data"]["url"]

    # see if user exists
    user_id = getUserID(login_session['email'])

    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']

    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '

    flash("Now logged in as %s" % login_session['username'])
    return output

@app.route('/fbdisconnect')
def fbdisconnect():
    facebook_id = login_session['facebook_id']
    # The access token must me included to successfully logout
    access_token = login_session['access_token']
    url = 'https://graph.facebook.com/%s/permissions?access_token=%s' % (facebook_id,access_token)
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]
    return "you have been logged out"

@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            gdisconnect()
            del login_session['gplus_id']
            del login_session['credentials']
        if login_session['provider'] == 'facebook':
            fbdisconnect()
            del login_session['facebook_id']

        del login_session['username']
        del login_session['email']
        del login_session['picture']
        del login_session['user_id']
        del login_session['provider']
        flash("You have successfully been logged out.")
        return redirect(url_for('showCatagories'))
    else:
        flash("You were not logged in to begin with!")
        return redirect(url_for('showCatagories'))

# JSON APIs to view Restaurant Information
"""
@app.route('/catagory/<int:catagory_id>/CatagoryItem/JSON')
def catagoryJSON(catagory_id):
    catagory = session.query(Catagories).filter_by(catagory_id=catagory_id).one()
    items = session.query(CatagoryItem).filter_by(catagory_id=catagory_id).all()
    return jsonify(CatagoryItems=[i.serialize for i in items])

@app.route('/catagory/<int:catagory_id>/catagory_item/<int:catagory_item_id>/JSON')
def menuItemJSON(catagory_id, catagory_item_id):
    catagory_item = session.query(CatagoryItem).filter_by(id=catagory_item_id).one()
    return jsonify(catagory_item=catagory_item.serialize)

@app.route('/catagory/JSON')
def catagoryJSON():
    catagories = session.query(Catagories).all()
    return jsonify(catagories=[r.serialize for c in catagories])
"""
# Show all catagories
@app.route('/')
@app.route('/catagories')
def showCatagories():
    catagories = session.query(Catagories).order_by(asc(Catagories.name))
    #t = session.query(CatagoryItem).order_by(asc(CatagoryItem.name))
    items = session.query(Catagories, CatagoryItem).join(CatagoryItem, Catagories.id==CatagoryItem.category_id).order_by(CatagoryItem.id.desc())

    if 'username' not in login_session:
        return render_template('publicCatagories.html', catagories=catagories, items=items)
    else:
        return render_template('catagories.html', catagories=catagories, items=items)

# Create a new restaurant
@app.route('/catagories/new/', methods=['GET', 'POST'])
def newCatagory():
    if request.method == 'POST':
        newCatagory = Catagories(name=request.form['name'], user_id=login_session['user_id'])

        session.add(newCatagory)
        flash('New Catagory %s Successfully Created' % newCatagory.name)
        session.commit()
        return redirect(url_for('showCatagories'))
    else:
        return render_template('newCatagory.html')

# Edit a Category
@app.route('/catagory/<int:catagory_id>/edit/', methods=['GET', 'POST'])
def editCatagory(catagory_id):
    editedCatagory = session.query(Catagories).filter_by(id=catagory_id).one()
    print editedCatagory.name
    if request.method == 'POST':
        if request.form['name']:
            editedCatagory.name = request.form['name']
            flash('Catagory Successfully Edited %s' % editedCatagory.name)
            return redirect(url_for('showCatagories'))
    else:
        return render_template('editCatagory.html', category=editedCatagory)

# Delete a catagory
@app.route('/catagory/<int:catagory_id>/delete/', methods=['GET', 'POST'])
def deleteCatagory(catagory_id):
    catagoryToDelete = session.query(Catagories).filter_by(id=catagory_id).one()
    if catagoryToDelete.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert('You are not authorized to delete this catagory. Please create your own catagory in order to delete.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        itemCount = session.query(CatagoryItem).filter_by(id=catagory_id).count()
        Catagory = session.query(CatagoryItem).filter_by(category_id=catagory_id).first()
        if Catagory == None:
            session.delete(catagoryToDelete)
            flash('%s Successfully Deleted' % catagoryToDelete.name)
            session.commit()
            return redirect(url_for('showCatagories', catagory_id=catagory_id))
        else:
            return "<script>function myFunction() {alert('You must first remove all Category Items first. Please remove all items.');}</script><body onload='myFunction()''>"

    else:
        return render_template('deletecatagory.html', category=catagoryToDelete)

    return redirect(url_for('showCatagories', catagory_id=catagory_id))
#List out Category Items
@app.route('/catagory/<int:catagory_id>/')
@app.route('/catagory/<int:catagory_id>/CatagoryItem/')
def showCatagory(catagory_id):

    catagory = session.query(Catagories).filter_by(id=catagory_id).one()
    creator = getUserInfo(catagory.user_id)
    items = session.query(CatagoryItem).filter_by(category_id=catagory_id).all()
    count = session.query(CatagoryItem).filter_by(category_id=catagory_id).count()
    if 'username' not in login_session or creator.id != login_session['user_id']:
        return render_template('publicCatagoryItems.html', items=items, catagory=catagory, creator= creator, count=count)
    else:
        return render_template('catagoryItems.html', items=items, catagory=catagory, creator = creator, count=count)

# Create a new catagory item
@app.route('/catagory/<int:catagory_id>/CatagoryItem/new/', methods=['GET', 'POST'])
def newCatagoryItem(catagory_id):
    catagory = session.query(Catagories).filter_by(id=catagory_id).one()

    if request.method == 'POST':
        newItem = CatagoryItem(name=request.form['name'], description=request.form[
                           'description'], category_id=catagory.id, user_id=catagory.user_id)
        session.add(newItem)
        session.commit()
        flash('New Category %s Item Successfully Created' % (catagory.id))
        return redirect(url_for('showCatagory', catagory_id=catagory.id))
    else:
        return render_template('newCatagoryItem.html', catagory_id=catagory.id)

#Edit Category Items
@app.route('/catagory/<int:catagory_id>/catagory_item/<int:catagory_item_id>/edit', methods=['GET', 'POST'])
def editCatagoryItem(catagory_id, catagory_item_id):

    editedItem = session.query(CatagoryItem).filter_by(id=catagory_item_id).one()
    catagory = session.query(Catagories).filter_by(id=catagory_id).one()

    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        session.add(editedItem)
        session.commit()
        flash('Menu Item Successfully Edited')
        return redirect(url_for('showCatagoryItem', catagory_id=catagory_id))
    else:
        return render_template('editCatagory.html', catagory_id=catagory_id, catagory_item_id=catagory_item_id, item=editedItem)



#List out Category Items
@app.route('/catagory/<int:catagory_id>/')
@app.route('/catagory/<int:catagory_id>/CatagoryItem/<int:catagory_item_id>/description')
def showItemDescription(catagory_id, catagory_item_id):

    catagoryItemDescription = session.query(CatagoryItem).filter_by(id=catagory_item_id).one()
    catagory = session.query(Catagories).filter_by(id=catagory_id).one()
    creator = getUserInfo(catagory.user_id)
    print catagory_item_id
    if 'username' not in login_session or creator.id != login_session['user_id']:
        return render_template('publicItemDescription.html', items=catagoryItemDescription)
    else:
        return render_template('itemDescription.html', catagory_id=catagory_id, catagory_item_id=catagory_item_id, items=catagoryItemDescription, creator = creator)

# Modify Description of Category Items
@app.route('/catagory/<int:catagory_id>/CatagoryItem/<int:catagory_item_id>/description/edit', methods=['GET', 'POST'])
def editItemDescription(catagory_id, catagory_item_id):
    editedItem = session.query(CatagoryItem).filter_by(id=catagory_item_id).one()
    catagory = session.query(Catagories).filter_by(id=catagory_id).one()
    catagories = session.query(Catagories).all()
    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        category = request.form['catagories']
        categoryId = session.query(Catagories).filter_by(name=category).one()
        editedItem.category_id = categoryId.id
        session.add(editedItem)
        session.commit()
        flash('Catagory Item Successfully Edited')
        return redirect(url_for('showItemDescription', catagory_id=catagory_id, catagory_item_id=catagory_item_id))
    else:
        return render_template('editItemDescription.html', catagories=catagories, catagory_id=catagory_id, catagory_item_id=catagory_item_id, items=editedItem)

# Delete a menu item
@app.route('/catagory/<int:catagory_id>/catagory_item/<int:catagory_item_id>/delete', methods=['GET', 'POST'])
def deleteCatagoryItem(catagory_id, catagory_item_id):
    catagory = session.query(Catagories).filter_by(id=catagory_id).one()
    itemToDelete = session.query(CatagoryItem).filter_by(id=catagory_item_id).one()

    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        flash('Catagory Item Successfully Deleted')
        return redirect(url_for('showCatagory', catagory_id=catagory_id))
    else:
        return render_template('deleteCatagoryItem.html', item=itemToDelete)

    #editedItemDescription = session.query(CatagoryItem).filter_by(id=catagory_item_id).first()
    #catagory = session.query(Catagories).filter_by(id=catagory_id).first()
    #catagory = session.query(Catagories).filter_by(id=catagory_id).one()
    #creator = getUserInfo(catagory.user_id)
    #if request.method == 'POST':
    #    editedItemDescription.name = catagory.name
    #    if request.form['description']:
    #        editedItem.description = request.form['description']
    #    session.add(editedItem)
    #    session.commit()
    #    flash('Catagory Item Successfully Edited')
    #    return redirect(url_for('showCatagory', catagory_id=catagory_id))
    #else:
    #    return render_template('editItemDescription.html', catagory=catagory, items=editedItemDescription, creator = creator)

def getUserID(email):
    try:
        user = session.query(User).filter_by(email = email).one()
        return user.id
    except:
        return None

def getUserInfo(user_id):
    user = session.query(User).filter_by(id = user_id).one()
    return user

def createUser(login_session):
    newUser = User(name = login_session['username'], email = login_session['email'], picture = login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email = login_session['email']).one()
    return user.id

if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=8000)
