-- first migration
-- depends: 

create table generated_book
(
	id integer
		constraint generated_book_pk
			primary key autoincrement,
	uuid text,
	at datetime,
	num_items int,
	meta text
);

create unique index generated_book_uuid_uindex
	on generated_book (uuid);


create table generated_book_format
(
    book_id integer not null
        references generated_book,
    file_name text not null,
    file_size integer not null,
    mimetype text not null
);

create table hn_best_story
(
	item_id integer not null,
	day date not null
);

create unique index hn_best_story_item_id_uindex
	on hn_best_story (item_id);

create table item_book
(
	book_id integer not null
		references generated_book,
	item_id integer not null
		constraint item_book_hn_best_story_item_id_fk
			references hn_best_story (item_id)
);
