Vue.component('resource-listing', {
    delimiters: ['${', '}'],
    props:
        ['sample', 'itemcount', 'columns', 'labels', 'resources', 'filterKey'],
    template: '#resource-listing-template',
    data: function () {
        this.itemcount ? this.numItems = this.itemcount : this.numItems = 0;
        let sortOrders = {};
        this.columns.forEach(function (key) {
          sortOrders[key] = 1
        });
        return {
            sortKey: '',
            resTypeDict: {
                // TODO: Expand this dictionary with the rest of the resource types
                "Composite Resource": "composite",
                "Generic": "generic",
                "Geopgraphic Raster": "geographicraster",
                "Model Program Resource": "modelprogram",
                "Collection Resource": "collection",
                "Web App Resource": "webapp",
                "Time Series": "timeseries",
                "Model Instance Resource": "modelinstance",
                "SWAT Model Instance Resource": "swat",
                "MODFLOW Model Instance Resource": "modflow",
                "Multidimensional (NetCDF)": "multidimensional"

            },
            sortOrders: sortOrders
        }
    },
    computed: {
        filteredResources: function () {
            let vue = this;
            let sortKey = this.sortKey;
            // let filterKey = this.filterKey && this.filterKey.toLowerCase();
            let order = this.sortOrders[sortKey] || 1;
            let resources = JSON.parse(this.sample);  // TODO validation, security, error handling
            // if (filterKey) {
            //     resources = resources.filter(function (row) {
            //         return Object.keys(row).some(function (key) {
            //             return String(row[key]).toLowerCase().indexOf(filterKey) > -1
            //         })
            //     })
            // }
            if (sortKey) {
                resources = resources.slice().sort(function (a, b) {
                    a = a[sortKey];
                    b = b[sortKey];
                    return (a === b ? 0 : a > b ? 1 : -1) * order
                })
            }

            console.log(resources);

            // Vue.set('numItems', 2);
            vue.numItems = resources.length;
            return resources
        },
    },
    filters: {
        capitalize: function (str) {
            if (str !== "link" && str !== "author_link") {  // TODO instead of iterating through headings, explicitly choose and display
                return str.charAt(0).toUpperCase() + str.slice(1)
            }
        },
        date: function (date) {
            return date;
        }
    },
    methods: {
        sortBy: function (key) {
            this.sortKey = key;
            this.sortOrders[key] = this.sortOrders[key] * -1
        }
    }
});
