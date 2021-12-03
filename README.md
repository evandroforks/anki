# Anki

[![Build status](https://badge.buildkite.com/c9edf020a4aec976f9835e54751cc5409d843adbb66d043bd3.svg?branch=main)](https://buildkite.com/ankitects/anki-ci)

This repo contains the source code for the computer version of Anki.

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see https://betas.ankiweb.net/

For more information on building, please see [Development](./docs/development.md).

> iniju, Re: Help understanding acronyms on anki database, https://groups.google.com/g/anki-android/c/pxcjf9in18I
> Oct 11, 2012, 6:28:58 PM
> to AnkiDroid, que...@fluidshopping.com
> Not sure about all of them, since this is port of libanki and the names were decided by Damien, but the cryptic ones:
> 1. crt: created time
> 1. ver: collection version
> 1. scm: schema version
> 1. dty: dirty flag?
> 1. usn: universal serial number, used during syncs
> 1. dconf: deck configuration
> 1. mid: model id
> 1. cid: card id
> 1. nid: note id
> 1. did: deck id
> 1. oid: old id
> 1. odid: old deck id
> 1. ivl: interval
> 1. reps: number of repetitions
> 1. ord: ordinal?
> 1. csum: checksum
> 1. flds: fields
> 1. odue: old due value
>
> But all this comes from libanki of the anki project, so you're probably better off if you base your analysis on the original.
>
> Cheers
> Kostas
>
>
> > On Tuesday, 9 October 2012 20:56:04 UTC+1, urlwolf wrote:
> > Hi,
> > First of all, congrats on ankiDroid 2. I've used ankiDroid since Jan 2011 and the improvements in speed are very noticeable.
> >
> > I'm considering whether it'd be possible to write a webapp (unrelated to languages) that would interface with anki/ankiDroid. For that, I'm thinking the scheduler algo must be mostly the same. Is this correct?
> >
> > I'm reading the code. First I want to understand the database. I guess the place to start would be:
> > ```
> > private static void _addSchema(AnkiDb db, boolean setColConf) {
> >         db.execute("create table if not exists col ( " + "id              integer primary key, "
> >                 + "crt             integer not null," + "mod             integer not null,"
> >                 + "scm             integer not null," + "ver             integer not null,"
> >                 + "dty             integer not null," + "usn             integer not null,"
> >                 + "ls              integer not null," + "conf            text not null,"
> >                 + "models          text not null," + "decks           text not null,"
> >                 + "dconf           text not null," + "tags            text not null" + ");");
> >         db.execute("create table if not exists notes (" + "   id              integer primary key,"
> >                 + "  guid            text not null," + " mid             integer not null,"
> >                 + " mod             integer not null," + " usn             integer not null,"
> >                 + " tags            text not null," + " flds            text not null,"
> >                 + " sfld            integer not null," + " csum            integer not null,"
> >                 + " flags           integer not null," + " data            text not null" + ");");
> >         db.execute("create table if not exists cards (" + "   id              integer primary key,"
> >                 + "  nid             integer not null," + "  did             integer not null,"
> >                 + "  ord             integer not null," + "  mod             integer not null,"
> >                 + " usn             integer not null," + " type            integer not null,"
> >                 + " queue           integer not null," + "    due             integer not null,"
> >                 + "   ivl             integer not null," + "  factor          integer not null,"
> >                 + " reps            integer not null," + "   lapses          integer not null,"
> >                 + "   left            integer not null," + "   odue            integer not null,"
> >                 + "   odid            integer not null," + "   flags           integer not null,"
> >                 + "   data            text not null" + ");");
> >         db.execute("create table if not exists revlog (" + "   id              integer primary key,"
> >                 + "   cid             integer not null," + "   usn             integer not null,"
> >                 + "   ease            integer not null," + "   ivl             integer not null,"
> >                 + "   lastIvl         integer not null," + "   factor          integer not null,"
> >                 + "   time            integer not null," + "   type            integer not null" + ");");
> >         db.execute("create table if not exists graves (" + "    usn             integer not null,"
> >                 + "    oid             integer not null," + "    type            integer not null" + ")");
> >         db.execute("INSERT OR IGNORE INTO col VALUES(1,0,0," +
> >                 Utils.intNow(1000) + "," + Collection.SCHEMA_VERSION +
> >                 ",0,0,0,'','{}','','','{}')");
> >         if (setColConf) {
> >             _setColVars(db);
> >         }
> >     }
> > ```
> >
> > But  the column names don't make any sense to me. They look like acronyms.
> > Is this documented anywhere? If no documentation (no worries!) Is there any other way I could guess the names?
> >
> > Thanks!
