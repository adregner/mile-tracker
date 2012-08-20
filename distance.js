var year = '2012';

Event.observe(window, 'dom:loaded', function() {
    new Ajax.Request('distance.py/dest', {
        method: 'GET',
        onSuccess: function(transport) {
            destinations.update(transport.responseJSON);
        }
    });
    
    var month = 0;
    $$('table.month').each(function(tbl_month) {
        month += 1;
        if(month > 5) {
            tbl_month.remove();
            return;
        }
        tbl_month.select('td.sun', 'td.mon', 'td.tue', 'td.wed', 'td.thu', 'td.fri', 'td.sat').each(function(td_day) {
            var day = td_day.innerHTML;
            var date_s = year+'-'+zero_pad(''+month)+'-'+zero_pad(day);
            td_day.update("<a href=\"javascript:;;\" id=\"day-"+date_s+"\" onclick=\"select_day('"+year+"', '"+month+"', '"+day+"')\">"+day+"</a>")
        });
    });
    
    if(window.location.hash) {
        select_day(window.location.hash.substring(1));
    }
});

var destinations = $H({});
var visits_log = $A();
var date;

function select_day(year, month, day) {
    $('distance').update();
    if($('day-'+date)) $('day-'+date).removeClassName('selected');
    if(year.length > 4)
        date = year;
    else
        date = year+'-'+zero_pad(month)+'-'+zero_pad(day);
    $('day-'+date).addClassName('selected')
    $('date').innerHTML = pretty_date(date);
    window.location.hash = date;
    new Ajax.Request('distance.py/day/'+date, {
        method: 'GET',
        onSuccess: function(transport) {
            visits_log = transport.responseJSON;
            draw_day();
        }
    });
}

function select_dest(dest_id) {
    $('distance').update()
    new Ajax.Request('distance.py/goto', {
        method: 'POST',
        parameters: $H({dest:dest_id, date:date}),
        onSuccess: function() {
            select_day(date);
        }
    });
}

function draw_day() {
    $('visits').update();
    if(visits_log.size() == 0) return;
    visits_log.each(function(v) {
        $('visits').insert("<a href=\"distance.py/delete/visit/"+v['id']+"\">x</a> <!-- "+v['day']+" #"+v['time']+": -->"+destinations.get(v['dest_id']).name+"<br/>");
    });
    
    new Ajax.Request('distance.py/miles/'+date, {
        method: 'GET',
        onSuccess: function(transport) {
            $('distance').update(transport.responseJSON.miles + ' Miles')
        }
    })
}

function pretty_date(d) {
    var parts = d.split('-');
    var thisDate = new Date(parts[0], parts[1]-1, parts[2], 13, 0, 0);
    return thisDate.toLocaleDateString();
}

function zero_pad(s) {
    if(s.length < 2) {
        return '0'+s;
    }
    return s;
}
